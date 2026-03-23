"""
services/openai_service.py
──────────────────────────
ONLINE MODE — OpenAI GPT-4o-mini (official SDK, strict JSON).
Fallback chain: OpenAI → Ollama → Heuristic.
"""

import json

from fastapi import HTTPException
from openai import OpenAI, RateLimitError, AuthenticationError, APIError

from config import logger
from utils.helpers import safe_str, safe_int
from services.ollama_service import ollama_analyze_risk, ollama_analyze_automation
from services.heuristic_service import heuristic_risk, heuristic_automation


# ── Shared field extractors ──────────────────────────────────────────────────

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


# ── Core SDK caller ──────────────────────────────────────────────────────────

def call_openai_sdk(prompt: str, api_key: str, system: str) -> str:
    """Call GPT-4o-mini with JSON response format enforced."""
    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=200,
    )
    return response.choices[0].message.content


# ── Public analysis functions ────────────────────────────────────────────────

def openai_analyze_risk(row: dict, api_key: str) -> dict:
    title, description, steps, severity = _extract_risk_fields(row)
    system = (
        "You are a senior QA risk analyst. Respond with valid JSON only. "
        "Keys: risk_score (int 1-10), priority (P1|P2|P3), explanation (string). "
        "P1=8-10 critical, P2=5-7 moderate, P3=1-4 low."
    )
    prompt = f"Title: {title}\nDescription: {description}\nSteps: {steps}\nSeverity: {severity}"
    try:
        raw     = call_openai_sdk(prompt, api_key, system)
        parsed  = json.loads(raw)
        score   = safe_int(parsed.get("risk_score") or 5, default=5, lo=1, hi=10)
        priority = str(parsed.get("priority") or "").strip()
        if priority not in ("P1", "P2", "P3"):
            priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        return {"risk_score": score, "priority": priority, "explanation": explanation,
                "mode": "online", "source": "openai"}
    except RateLimitError:
        logger.warning(f"OpenAI rate limited — falling back to Ollama for: {title[:40]}")
        result = ollama_analyze_risk(title, description, steps, severity) or \
                 heuristic_risk(title, description, steps, severity)
        result["mode"] = "online-fallback"
        return result
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.")
    except (APIError, Exception) as e:
        logger.warning(f"OpenAI error — falling back to Ollama: {e}")
        result = ollama_analyze_risk(title, description, steps, severity) or \
                 heuristic_risk(title, description, steps, severity)
        result["mode"] = "online-fallback"
        return result


def openai_analyze_automation(row: dict, api_key: str) -> dict:
    title, description, steps = _extract_auto_fields(row)
    system = (
        "You are a senior QA automation architect. Respond with valid JSON only. "
        "Keys: suitability (Automatable|Partial|Not Suitable), confidence (int 0-100), explanation (string). "
        "Automatable=stable repeatable, Partial=some dynamic elements, Not Suitable=needs human/OTP/biometric."
    )
    prompt = f"Title: {title}\nDescription: {description}\nSteps: {steps}"
    try:
        raw         = call_openai_sdk(prompt, api_key, system)
        parsed      = json.loads(raw)
        suitability = str(parsed.get("suitability") or "").strip()
        if suitability not in ("Automatable", "Partial", "Not Suitable"):
            suitability = "Partial"
        confidence  = safe_int(parsed.get("confidence") or 50, default=50, lo=0, hi=100)
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        return {"suitability": suitability, "confidence": confidence, "explanation": explanation,
                "mode": "online", "source": "openai"}
    except RateLimitError:
        logger.warning(f"OpenAI rate limited — falling back to Ollama for: {title[:40]}")
        result = ollama_analyze_automation(title, description, steps) or \
                 heuristic_automation(title, description, steps)
        result["mode"] = "online-fallback"
        return result
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.")
    except (APIError, Exception) as e:
        logger.warning(f"OpenAI error for '{title[:40]}': {e} — falling back")
        result = ollama_analyze_automation(title, description, steps) or \
                 heuristic_automation(title, description, steps)
        result["mode"] = "online-fallback"
        return result
