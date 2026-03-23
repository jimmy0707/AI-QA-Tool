"""
services/gemini_service.py
──────────────────────────
GEMINI MODE — Google Gemini AI (google-genai SDK).

Features:
  - Sliding-window rate limiter  (5 RPM free tier)
  - Model auto-discovery + per-key cache  (list_models once, never per request)
  - Precise error classification  (quota / network / invalid-key never confused)
  - Safe JSON parser  (empty / malformed response → fallback, never crash)
  - Fallback chain: Gemini → Ollama → Heuristic
"""

import json
import time
import threading
import collections

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
_gemini_model_cache: dict = {}        # key_fingerprint → model_name string
_gemini_list_lock         = threading.Lock()
_gemini_rpm_limit         = 5         # max requests per 60 s (free tier)
_gemini_rpm_window        = 60.0      # seconds
_gemini_timestamps: dict  = {}        # key_fingerprint → deque of monotonic timestamps
_gemini_rate_lock         = threading.Lock()


# ── Rate limiter ──────────────────────────────────────────────────────────────

def _gemini_rate_wait(key_fingerprint: str):
    """
    Block the calling thread until it is safe to fire another Gemini request.
    Implements a sliding-window limiter capped at _gemini_rpm_limit RPM.
    Called from ThreadPoolExecutor workers — time.sleep() is intentional.
    """
    with _gemini_rate_lock:
        if key_fingerprint not in _gemini_timestamps:
            _gemini_timestamps[key_fingerprint] = collections.deque()
        timestamps = _gemini_timestamps[key_fingerprint]

        now = time.monotonic()
        while timestamps and now - timestamps[0] >= _gemini_rpm_window:
            timestamps.popleft()

        if len(timestamps) >= _gemini_rpm_limit:
            wait = _gemini_rpm_window - (now - timestamps[0]) + 0.1
            logger.info(f"[Gemini] Rate limit — waiting {wait:.1f}s (5 RPM free tier)")
            time.sleep(wait)
            now = time.monotonic()
            while timestamps and now - timestamps[0] >= _gemini_rpm_window:
                timestamps.popleft()

        timestamps.append(time.monotonic())


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
        tier    = 0 if "flash" in n else 1 if "pro" in n else 2
        version = 0 if "2.0" in n else 1 if "1.5" in n else 2 if "1.0" in n else 3
        latest  = 0 if "latest" in n else 1
        return (tier, version, latest)

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
    On 404 (model retired), clears cache and rediscovers once automatically.
    """
    key_fingerprint = api_key[-8:]
    client          = genai.Client(api_key=api_key)

    _gemini_rate_wait(key_fingerprint)
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
        return _call(model_name)
    except Exception as e:
        if "404" in str(e) or "NOT_FOUND" in str(e):
            logger.warning(f"[Gemini] Model '{model_name}' gone — rediscovering...")
            with _gemini_list_lock:
                _gemini_model_cache.pop(key_fingerprint, None)
            model_name = _get_gemini_model(client, key_fingerprint)
            return _call(model_name)
        raise


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
        if error_type == "invalid_key":
            logger.warning(f"[Gemini] Invalid API key for '{title[:40]}'")
            raise HTTPException(status_code=401, detail="Invalid Gemini API key.")
        elif error_type == "quota":
            logger.warning(f"[Gemini] Quota/rate-limit for '{title[:40]}' — falling back to Ollama")
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
        if error_type == "invalid_key":
            logger.warning(f"[Gemini] Invalid API key for '{title[:40]}'")
            raise HTTPException(status_code=401, detail="Invalid Gemini API key.")
        elif error_type == "quota":
            logger.warning(f"[Gemini] Quota/rate-limit for '{title[:40]}' — falling back to Ollama")
        elif error_type == "network":
            logger.warning(f"[Gemini] Network error for '{title[:40]}': {e} — falling back")
        else:
            logger.warning(f"[Gemini] Fallback for '{title[:40]}': {e}")

        result = ollama_analyze_automation(title, description, steps) or \
                 heuristic_automation(title, description, steps)
        result["mode"] = "gemini-fallback"
        return result
