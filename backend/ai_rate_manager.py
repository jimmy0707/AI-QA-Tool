

import asyncio
import hashlib
import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("ai-qa-platform")


# ─────────────────────────────────────────────
# Config — tune these for your API tier
# ─────────────────────────────────────────────
class RateLimitConfig:
    # OpenAI free tier: ~3 RPM, ~200 RPD
    OPENAI_REQUESTS_PER_MINUTE = 3
    OPENAI_REQUESTS_PER_DAY    = 200

    # Gemini free tier: ~15 RPM, 1500 RPD
    GEMINI_REQUESTS_PER_MINUTE = 15
    GEMINI_REQUESTS_PER_DAY    = 1500

    # Queue settings
    MAX_QUEUE_SIZE   = 100     # max pending requests
    REQUEST_TIMEOUT  = 120     # seconds to wait in queue before giving up

    # Retry settings
    MAX_RETRIES      = 3
    BASE_RETRY_DELAY = 2.0     # seconds — doubles each retry (exponential backoff)

    # Cache settings
    CACHE_TTL_SECONDS = 3600   # 1 hour — same test case = same result


# ─────────────────────────────────────────────
# Priority levels for request queue
# ─────────────────────────────────────────────
class Priority(Enum):
    HIGH   = 1   # Single test case / real-time
    NORMAL = 2   # Small batch (< 10 cases)
    LOW    = 3   # Large batch (10+ cases)


# ─────────────────────────────────────────────
# Token Bucket — controls request rate
# ─────────────────────────────────────────────
class TokenBucket:
    """
    Token Bucket algorithm:
    - Bucket fills at a fixed rate (e.g. 3 tokens/minute for OpenAI)
    - Each API call consumes 1 token
    - If bucket is empty → wait until refilled
    """
    def __init__(self, rpm: int, name: str):
        self.name        = name
        self.rpm         = rpm
        self.tokens      = float(rpm)
        self.max_tokens  = float(rpm)
        self.refill_rate = rpm / 60.0       # tokens per second
        self.last_refill = time.monotonic()
        self._lock       = asyncio.Lock()

        # Daily limit tracking
        self.daily_count    = 0
        self.daily_reset_at = time.monotonic() + 86400

    def _refill(self):
        now     = time.monotonic()
        elapsed = now - self.last_refill
        gained  = elapsed * self.refill_rate
        self.tokens      = min(self.max_tokens, self.tokens + gained)
        self.last_refill = now

    def _reset_daily_if_needed(self):
        if time.monotonic() >= self.daily_reset_at:
            self.daily_count    = 0
            self.daily_reset_at = time.monotonic() + 86400
            logger.info(f"[{self.name}] Daily request counter reset")

    async def acquire(self, daily_limit: int) -> float:
        """
        Wait until a token is available.
        Returns the number of seconds we waited.
        """
        async with self._lock:
            self._reset_daily_if_needed()

            # Hard stop if daily limit hit
            if self.daily_count >= daily_limit:
                wait = self.daily_reset_at - time.monotonic()
                raise RuntimeError(
                    f"{self.name} daily limit reached ({daily_limit} requests). "
                    f"Resets in {int(wait/3600)}h {int((wait%3600)/60)}m."
                )

            self._refill()
            wait_time = 0.0

            # Wait for token to become available
            while self.tokens < 1.0:
                needed = (1.0 - self.tokens) / self.refill_rate
                logger.info(f"[{self.name}] Rate limit — waiting {needed:.1f}s for token")
                await asyncio.sleep(needed)
                self._refill()
                wait_time += needed

            self.tokens      -= 1.0
            self.daily_count += 1
            logger.info(
                f"[{self.name}] Token consumed. "
                f"Remaining: {self.tokens:.1f}/{self.max_tokens} | "
                f"Daily: {self.daily_count}/{daily_limit}"
            )
            return wait_time


# ─────────────────────────────────────────────
# Response Cache — avoids duplicate API calls
# ─────────────────────────────────────────────
class ResponseCache:
    """
    In-memory LRU cache for AI responses.
    Key = hash of (provider + prompt content)
    Same test case title + description = same cache key = instant response.

    Production upgrade: replace with Redis for multi-server support.
    """
    def __init__(self, max_size: int = 500, ttl: int = 3600):
        self.max_size  = max_size
        self.ttl       = ttl
        self._cache: Dict[str, Dict] = {}   # key → {value, expires_at}
        self._order    = deque()             # LRU tracking

    def _make_key(self, provider: str, prompt: str) -> str:
        """Stable hash key from provider + prompt."""
        raw = f"{provider}:{prompt.strip().lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, provider: str, prompt: str) -> Optional[Any]:
        key = self._make_key(provider, prompt)
        entry = self._cache.get(key)
        if entry and time.monotonic() < entry["expires_at"]:
            # Move to end (most recently used)
            try:
                self._order.remove(key)
            except ValueError:
                pass
            self._order.append(key)
            logger.info(f"[Cache] HIT for {provider} — saved 1 API call")
            return entry["value"]
        if entry:
            # Expired — remove
            del self._cache[key]
        return None

    def set(self, provider: str, prompt: str, value: Any):
        key = self._make_key(provider, prompt)
        # Evict oldest if full
        while len(self._cache) >= self.max_size:
            oldest = self._order.popleft()
            self._cache.pop(oldest, None)
        self._cache[key] = {
            "value":      value,
            "expires_at": time.monotonic() + self.ttl,
        }
        self._order.append(key)
        logger.info(f"[Cache] STORED {provider} response (cache size: {len(self._cache)})")

    def stats(self) -> Dict:
        valid = sum(1 for e in self._cache.values() if time.monotonic() < e["expires_at"])
        return {"total_entries": len(self._cache), "valid_entries": valid, "max_size": self.max_size}


# ─────────────────────────────────────────────
# Queued Request — one unit of work
# ─────────────────────────────────────────────
@dataclass(order=True)
class QueuedRequest:
    priority:   int                      # lower = higher priority
    created_at: float = field(compare=False, default_factory=time.monotonic)
    request_id: str   = field(compare=False, default="")
    provider:   str   = field(compare=False, default="")
    prompt:     str   = field(compare=False, default="")
    fn:         Any   = field(compare=False, default=None)  # callable
    future:     Any   = field(compare=False, default=None)  # asyncio.Future


# ─────────────────────────────────────────────
# AI Rate Manager — the main orchestrator
# ─────────────────────────────────────────────
class AIRateManager:
    """
    Central manager that:
    1. Checks cache before any API call
    2. Queues requests if rate limit is close
    3. Uses token buckets to pace API calls
    4. Retries with exponential backoff on failure
    5. Returns cached results instantly to save quota
    """

    def __init__(self):
        self.cache = ResponseCache(
            max_size=500,
            ttl=RateLimitConfig.CACHE_TTL_SECONDS
        )
        self.buckets: Dict[str, TokenBucket] = {}
        self._queue: asyncio.PriorityQueue = None
        self._worker_task = None
        self._stats = {
            "total_requests":  0,
            "cache_hits":      0,
            "api_calls":       0,
            "rate_limit_hits": 0,
            "retries":         0,
            "errors":          0,
        }

    async def initialize(self):
        """Call once on FastAPI startup."""
        self._queue = asyncio.PriorityQueue(maxsize=RateLimitConfig.MAX_QUEUE_SIZE)
        self.buckets = {
            "openai": TokenBucket(RateLimitConfig.OPENAI_REQUESTS_PER_MINUTE, "OpenAI"),
            "gemini": TokenBucket(RateLimitConfig.GEMINI_REQUESTS_PER_MINUTE, "Gemini"),
        }
        self._worker_task = asyncio.create_task(self._queue_worker())
        logger.info(
            f"AIRateManager initialized — "
            f"OpenAI: {RateLimitConfig.OPENAI_REQUESTS_PER_MINUTE} RPM | "
            f"Gemini: {RateLimitConfig.GEMINI_REQUESTS_PER_MINUTE} RPM | "
            f"Cache TTL: {RateLimitConfig.CACHE_TTL_SECONDS}s"
        )

    async def shutdown(self):
        if self._worker_task:
            self._worker_task.cancel()

    # ── Public API ──

    async def call(
        self,
        provider: str,          # "openai" or "gemini"
        prompt: str,
        fn: Callable,           # the actual API call function
        priority: Priority = Priority.NORMAL,
        use_cache: bool = True,
    ) -> Any:
        """
        Main entry point. Call this instead of calling AI APIs directly.

        Flow:
          1. Check cache → return instantly if hit
          2. Enqueue request with priority
          3. Worker picks it up when token is available
          4. Retry on failure with exponential backoff
          5. Store result in cache
        """
        self._stats["total_requests"] += 1

        # Step 1: Cache check
        if use_cache:
            cached = self.cache.get(provider, prompt)
            if cached is not None:
                self._stats["cache_hits"] += 1
                return cached

        # Step 2: Enqueue
        loop   = asyncio.get_event_loop()
        future = loop.create_future()
        req    = QueuedRequest(
            priority   = priority.value,
            request_id = str(uuid.uuid4() if False else id(future))[:8],
            provider   = provider,
            prompt     = prompt,
            fn         = fn,
            future     = future,
        )

        try:
            self._queue.put_nowait(req)
            logger.info(
                f"[Queue] Enqueued {provider} request "
                f"(priority={priority.name}, queue_size={self._queue.qsize()})"
            )
        except asyncio.QueueFull:
            self._stats["errors"] += 1
            raise RuntimeError(
                f"Request queue is full ({RateLimitConfig.MAX_QUEUE_SIZE} pending). "
                "Please try again in a moment."
            )

        # Step 3: Wait for result (with timeout)
        try:
            result = await asyncio.wait_for(future, timeout=RateLimitConfig.REQUEST_TIMEOUT)
            if use_cache and result is not None:
                self.cache.set(provider, prompt, result)
            return result
        except asyncio.TimeoutError:
            self._stats["errors"] += 1
            raise RuntimeError(
                f"Request timed out after {RateLimitConfig.REQUEST_TIMEOUT}s. "
                "The AI service may be overloaded."
            )

    # ── Internal Queue Worker ──

    async def _queue_worker(self):
        """
        Continuously processes queued requests one at a time.
        Respects token buckets — waits automatically if rate limit is close.
        """
        logger.info("[Queue Worker] Started")
        while True:
            try:
                req: QueuedRequest = await self._queue.get()

                # Check if request already timed out while in queue
                age = time.monotonic() - req.created_at
                if age > RateLimitConfig.REQUEST_TIMEOUT:
                    if not req.future.done():
                        req.future.set_exception(
                            RuntimeError(f"Request expired after {age:.0f}s in queue")
                        )
                    self._queue.task_done()
                    continue

                # Acquire token (waits automatically if rate limit close)
                bucket = self.buckets.get(req.provider)
                if bucket:
                    daily_limit = (
                        RateLimitConfig.OPENAI_REQUESTS_PER_DAY
                        if req.provider == "openai"
                        else RateLimitConfig.GEMINI_REQUESTS_PER_DAY
                    )
                    try:
                        await bucket.acquire(daily_limit)
                    except RuntimeError as e:
                        if not req.future.done():
                            req.future.set_exception(e)
                        self._queue.task_done()
                        continue

                # Execute with retry
                result = await self._execute_with_retry(req)
                if not req.future.done():
                    if isinstance(result, Exception):
                        req.future.set_exception(result)
                    else:
                        req.future.set_result(result)

                self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("[Queue Worker] Stopped")
                break
            except Exception as e:
                logger.error(f"[Queue Worker] Unexpected error: {e}")

    async def _execute_with_retry(self, req: QueuedRequest) -> Any:
        """
        Execute API call with exponential backoff retry.

        Retry schedule:
          Attempt 1: immediate
          Attempt 2: wait 2s
          Attempt 3: wait 4s
          Attempt 4: wait 8s → give up
        """
        delay = RateLimitConfig.BASE_RETRY_DELAY

        for attempt in range(1, RateLimitConfig.MAX_RETRIES + 1):
            try:
                self._stats["api_calls"] += 1
                # Run the blocking API call in a thread (non-blocking for event loop)
                loop   = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, req.fn)
                logger.info(
                    f"[{req.provider.upper()}] Request {req.request_id} succeeded "
                    f"(attempt {attempt})"
                )
                return result

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = any(kw in err_str for kw in ["rate", "429", "quota", "too many", "limit"])
                is_retryable  = is_rate_limit or any(kw in err_str for kw in ["timeout", "503", "502", "server error"])

                if is_rate_limit:
                    self._stats["rate_limit_hits"] += 1

                if attempt < RateLimitConfig.MAX_RETRIES and is_retryable:
                    self._stats["retries"] += 1
                    logger.warning(
                        f"[{req.provider.upper()}] Attempt {attempt} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    delay *= 2   # exponential backoff
                else:
                    logger.error(
                        f"[{req.provider.upper()}] All {attempt} attempts failed: {e}"
                    )
                    self._stats["errors"] += 1
                    return e    # Return exception — caller handles it

    # ── Stats & Monitoring ──

    def get_stats(self) -> Dict:
        cache_hit_rate = (
            round(self._stats["cache_hits"] / self._stats["total_requests"] * 100)
            if self._stats["total_requests"] > 0 else 0
        )
        return {
            **self._stats,
            "cache_hit_rate_pct": cache_hit_rate,
            "queue_size":         self._queue.qsize() if self._queue else 0,
            "cache_stats":        self.cache.stats(),
            "token_buckets": {
                name: {
                    "tokens_available": round(bucket.tokens, 2),
                    "max_tokens":       bucket.max_tokens,
                    "daily_used":       bucket.daily_count,
                }
                for name, bucket in self.buckets.items()
            },
        }


# Singleton — import this everywhere
ai_manager = AIRateManager()