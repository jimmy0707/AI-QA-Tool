"""
services/gemini_service.py
──────────────────────────
GEMINI MODE — Google Gemini AI (google-genai SDK).

Features:
  - Serial token-bucket rate limiter (5 RPM = 1 call every 12 s)
  - Model auto-discovery + per-key cache  (list_models once, never per request)
  - Precise error classification  (quota / network / invalid-key never confused)
  - Safe JSON parser  (empty / malformed response → fallback, never crash)
  - Fallback chain: Gemini → Ollama → Heuristic

WHY SERIAL (not parallel) FOR GEMINI FREE TIER
───────────────────────────────────────────────
With 8 parallel workers and a sliding-window limiter, all threads grab their
rate-limit slot at nearly the same moment and fire simultaneously — Google
sees a burst and returns 429 RESOURCE_EXHAUSTED for most of them even though
our counter said "5 slots available".

The fix: a single global threading.Lock() (_gemini_call_lock) so only ONE
thread calls Gemini at a time, and we hard-sleep 12 s between calls
(60 s ÷ 5 RPM = 12 s minimum gap). This is slower but 100% reliable on the
free tier. Workers queue up and wait their turn.
"""

import json
import time
import threading

from fastapi import HTTPException
from google import genai
from google.genai import types as genai_types

from config import logger
from utils.helpers import safe_str, safe_int
from services.ollama_service import ollama_analyze_risk, ollama_analyze_automation
from services.heuristic_service import heuristic_risk, heuristic_automation


# ── Shared field extractors (same pattern as OpenAI service) ─────────────────

def _extract_risk_fields(row: dict):
    title       = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps       = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    severity    = safe_str(row.get("severity") or row.get("Severity"), "")
    return title, description, steps, severity

def _extract_auto_fields(row: dict):
    title       = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps       = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    return title, description, steps


# ── Rate limiter state (module-level — shared across all threads) ─────────────
_gemini_model_cache: dict = {}    # key_fingerprint → model_name string
_gemini_list_lock         = threading.Lock()

# Serial call gate — only ONE Gemini request at a time across all workers
_gemini_call_lock         = threading.Lock()
_gemini_last_call_time    = 0.0   # monotonic timestamp of last completed call
_GEMINI_MIN_GAP           = 4.5   # seconds between calls (60s / 15 RPM + 0.5s buffer for 3.1-flash-lite)


# ── Rate limiter ──────────────────────────────────────────────────────────────

def _gemini_rate_wait(key_fingerprint: str):
    """
    Acquire the global Gemini call lock and wait until the minimum gap
    since the last call has elapsed.

    This serialises ALL Gemini calls across all ThreadPoolExecutor workers.
    Only one request fires at a time — the rest queue up here and wait.
    This is the only reliable way to respect 5 RPM on the free tier when
    multiple workers are running in parallel.
    """
    global _gemini_last_call_time

    # Acquire the lock — this blocks until the previous worker releases it
    _gemini_call_lock.acquire()

    # Now we hold the lock. Wait out the minimum gap.
    now     = time.monotonic()
    elapsed = now - _gemini_last_call_time
    if elapsed < _GEMINI_MIN_GAP:
        wait = _GEMINI_MIN_GAP - elapsed
        logger.info(f"[Gemini] Spacing calls — waiting {wait:.1f}s to stay within 5 RPM")
        time.sleep(wait)

    # Record the time this call starts — lock is released in call_gemini()
    _gemini_last_call_time = time.monotonic()


# ── Model discovery ───────────────────────────────────────────────────────────

def _discover_gemini_model(client) -> str:
    """
    Call list_models() ONCE and pick the best generateContent-capable model.
    Sorted by: flash > pro > other, 2.0 > 1.5 > 1.0, -latest > plain.
    """
    try:
        all_models = list(client.models.list())
    except Exception as e:
        raise RuntimeError(f"[Gemini] Cannot list models: {e}")

    supported = []
    for m in all_models:
        actions = (
            getattr(m, "supported_actions", None) or
            getattr(m, "supported_generation_methods", None) or
            []
        )
        if "generateContent" in actions:
            supported.append(m)

    if not supported:
        supported = all_models   # SDK doesn't expose actions — use full list

    names = [getattr(m, "name", None) or str(m) for m in supported]
    logger.info(f"[Gemini] Models available for generateContent: {names}")

    def _priority(name: str) -> tuple:
        n = name.lower()

        # Never pick these — wrong modality or no text generation
        SKIP = ["tts", "robotics", "computer-use", "deep-research",
                "nano-banana", "imagen", "veo", "embedding", "audio", "live"]
        if any(s in n for s in SKIP): return (9, 9, 9)
        if "image" in n and "flash-image" not in n: return (9, 9, 9)

        # PINNED FIRST: gemini-3.1-flash-lite — 15 RPM, 500 RPD (best free tier)
        if "3.1" in n and "flash-lite" in n: return (0, 0, 0)

        # Second choice: any other flash-lite
        if "flash-lite" in n: return (1, 0, 0)

        # Third: regular flash models
        if "flash" in n:
            version = 0 if "3"   in n else                       1 if "2.5" in n else                       2 if "2.0" in n else 3
            return (2, version, 0)

        # Last resort: pro models
        return (3, 0, 0)

    names.sort(key=_priority)
    if not names:
        raise RuntimeError("[Gemini] No generateContent-capable models found for this API key.")

    logger.info(f"[Gemini] Selected model: {names[0]}")
    return names[0]


def _get_gemini_model(client, key_fingerprint: str) -> str:
    """Return cached model name, discovering only on first call per API key."""
    with _gemini_list_lock:
        if key_fingerprint not in _gemini_model_cache:
            _gemini_model_cache[key_fingerprint] = _discover_gemini_model(client)
        return _gemini_model_cache[key_fingerprint]


# ── Safe JSON parser ──────────────────────────────────────────────────────────

def _safe_parse_gemini_json(raw: str, context: str) -> dict | None:
    """
    Return parsed dict or None — never raises.
    Strips accidental markdown fences Gemini sometimes adds.
    """
    if not raw or not raw.strip():
        logger.warning(f"[Gemini] Empty response for {context} — will fallback")
        return None
    try:
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"[Gemini] JSON parse failed for {context}: {e} | raw={raw[:80]!r}")
        return None


# ── Core caller ───────────────────────────────────────────────────────────────

def call_gemini(prompt: str, api_key: str) -> str:
    """
    Rate-limited, model-cached Gemini call.
    _gemini_rate_wait() acquires _gemini_call_lock — we ALWAYS release it
    in the finally block so the next queued worker can proceed.
    On 404 (model retired), clears cache and rediscovers once automatically.
    """
    key_fingerprint = api_key[-8:]
    client          = genai.Client(api_key=api_key)

    # Acquire the serial lock + enforce minimum gap between calls
    _gemini_rate_wait(key_fingerprint)

    try:
        model_name = _get_gemini_model(client, key_fingerprint)

        def _call(model: str) -> str:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=300,
                    response_mime_type="application/json",
                ),
            )
            return response.text or ""

        try:
            result = _call(model_name)
            logger.info(f"[Gemini] Call succeeded with {model_name}")
            return result
        except Exception as e:
            if "404" in str(e) or "NOT_FOUND" in str(e):
                logger.warning(f"[Gemini] Model '{model_name}' gone — rediscovering...")
                with _gemini_list_lock:
                    _gemini_model_cache.pop(key_fingerprint, None)
                model_name = _get_gemini_model(client, key_fingerprint)
                return _call(model_name)
            raise

    finally:
        # Always release so the next worker can proceed
        try:
            _gemini_call_lock.release()
        except RuntimeError:
            pass


# ── Error classifier ──────────────────────────────────────────────────────────

def _classify_gemini_error(e: Exception) -> str:
    """
    Map a Gemini exception to one of four labels so each is handled correctly.

    Returns
    ───────
    "invalid_key"  → key is genuinely wrong/revoked   → raise HTTP 401
    "quota"        → free-tier RPM or daily cap hit    → fallback silently
    "network"      → timeout, DNS, connection refused  → fallback silently
    "fallback"     → everything else                   → fallback silently

    Root cause of the original bug that prompted this function:
      "permission" matched inside "RESOURCE_EXHAUSTED" and "invalid" matched
      inside "invalid argument" — both quota messages — so quota errors were
      wrongly classified as auth failures and returned HTTP 401.
    """
    err = str(e).lower()

    AUTH_SIGNALS = [
        "api_key_invalid", "api key not valid", "invalid api key",
        "unauthenticated", "401",
    ]
    if any(sig in err for sig in AUTH_SIGNALS):
        return "invalid_key"

    QUOTA_SIGNALS = [
        "429", "resource_exhausted", "quota_exceeded", "ratelimitexceeded",
        "rate limit", "quota", "too many requests", "daily limit", "per minute",
    ]
    if any(sig in err for sig in QUOTA_SIGNALS):
        return "quota"

    NETWORK_SIGNALS = [
        "timeout", "timed out", "connection", "network", "dns", "socket",
        "unreachable", "name or service not known", "ssl", "certificate",
        "503", "502", "504",
    ]
    if any(sig in err for sig in NETWORK_SIGNALS):
        return "network"

    return "fallback"


# ── Public analysis functions ─────────────────────────────────────────────────

def gemini_analyze_risk(row: dict, api_key: str) -> dict:
    """
    Risk analysis via Gemini.
    Only raises HTTP 401 when the key is genuinely invalid.
    All other errors fall back silently to Ollama → Heuristic.
    """
    title, description, steps, severity = _extract_risk_fields(row)
    prompt = (
        "You are a senior QA risk analyst. Respond with valid JSON only.\n"
        f"Title: {title}\nDescription: {description}\nSteps: {steps}\nSeverity: {severity}\n\n"
        "Return exactly this JSON structure:\n"
        '{"risk_score": 7, "priority": "P2", "explanation": "one professional sentence"}\n'
        "Rules: risk_score integer 1-10. priority: P1 (score 8-10), P2 (5-7), P3 (1-4)."
    )
    try:
        raw    = call_gemini(prompt, api_key)
        parsed = _safe_parse_gemini_json(raw, title[:30])
        if parsed is None:
            raise ValueError("Empty or unparseable Gemini response")

        score    = safe_int(parsed.get("risk_score") or 5, default=5, lo=1, hi=10)
        priority = str(parsed.get("priority") or "").strip()
        if priority not in ("P1", "P2", "P3"):
            priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        logger.info(f"[Gemini] Risk: {title[:30]} → {priority} (score={score})")
        return {"risk_score": score, "priority": priority, "explanation": explanation,
                "mode": "gemini", "source": "gemini"}

    except Exception as e:
        error_type = _classify_gemini_error(e)
        logger.warning(f"[Gemini] FULL ERROR for '{title[:40]}': {type(e).__name__}: {e}")
        if error_type == "invalid_key":
            logger.warning(f"[Gemini] Invalid API key for '{title[:40]}'")
            raise HTTPException(status_code=401, detail="Invalid Gemini API key.")
        elif error_type == "quota":
            logger.warning(f"[Gemini] Quota exhausted for '{title[:40]}' — clearing model cache and falling back to Ollama")
            # Clear model cache — next request will rediscover a model with available quota
            key_fp = api_key[-8:]
            with _gemini_list_lock:
                _gemini_model_cache.pop(key_fp, None)
        elif error_type == "network":
            logger.warning(f"[Gemini] Network error for '{title[:40]}': {e} — falling back")
        else:
            logger.warning(f"[Gemini] Fallback for '{title[:40]}': {e}")

        result = ollama_analyze_risk(title, description, steps, severity) or \
                 heuristic_risk(title, description, steps, severity)
        result["mode"] = "gemini-fallback"
        return result


def gemini_analyze_automation(row: dict, api_key: str) -> dict:
    """
    Automation analysis via Gemini.
    Only raises HTTP 401 when the key is genuinely invalid.
    All other errors fall back silently to Ollama → Heuristic.
    """
    title, description, steps = _extract_auto_fields(row)
    prompt = (
        "You are a senior QA automation architect. Respond with valid JSON only.\n"
        f"Title: {title}\nDescription: {description}\nSteps: {steps}\n\n"
        "Return exactly this JSON structure:\n"
        '{"suitability": "Automatable", "confidence": 85, "explanation": "one professional sentence"}\n'
        "Rules: suitability must be exactly one of: Automatable, Partial, Not Suitable.\n"
        "Automatable=stable repeatable, no OTP/Captcha.\n"
        "Partial=some dynamic/external dependencies.\n"
        "Not Suitable=needs human judgment, OTP, Captcha, biometric, or physical hardware."
    )
    try:
        raw    = call_gemini(prompt, api_key)
        parsed = _safe_parse_gemini_json(raw, title[:30])
        if parsed is None:
            raise ValueError("Empty or unparseable Gemini response")

        suitability = str(parsed.get("suitability") or "").strip()
        if suitability not in ("Automatable", "Partial", "Not Suitable"):
            suitability = "Partial"
        confidence  = safe_int(parsed.get("confidence") or 50, default=50, lo=0, hi=100)
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        logger.info(f"[Gemini] Automation: {title[:30]} → {suitability} ({confidence}%)")
        return {"suitability": suitability, "confidence": confidence, "explanation": explanation,
                "mode": "gemini", "source": "gemini"}

    except Exception as e:
        error_type = _classify_gemini_error(e)
        logger.warning(f"[Gemini] FULL ERROR for '{title[:40]}': {type(e).__name__}: {e}")
        if error_type == "invalid_key":
            logger.warning(f"[Gemini] Invalid API key for '{title[:40]}'")
            raise HTTPException(status_code=401, detail="Invalid Gemini API key.")
        elif error_type == "quota":
            logger.warning(f"[Gemini] Quota exhausted for '{title[:40]}' — clearing model cache and falling back to Ollama")
            key_fp = api_key[-8:]
            with _gemini_list_lock:
                _gemini_model_cache.pop(key_fp, None)
        elif error_type == "network":
            logger.warning(f"[Gemini] Network error for '{title[:40]}': {e} — falling back")
        else:
            logger.warning(f"[Gemini] Fallback for '{title[:40]}': {e}")

        result = ollama_analyze_automation(title, description, steps) or \
                 heuristic_automation(title, description, steps)
        result["mode"] = "gemini-fallback"
        return result