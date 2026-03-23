"""
services/ollama_service.py
──────────────────────────
LAYER 1 — Local Ollama AI
Handles any test case; parses both JSON and plain-English responses.
Falls back gracefully on timeout or model error.
"""

import requests
from typing import Optional

from config import OLLAMA_URL, OLLAMA_MODEL_DEFAULT, logger
from utils.helpers import safe_str, safe_int, extract_json, parse_risk_from_text, parse_automation_from_text


def call_ollama(prompt: str, model: str = None) -> str:
    """Send a prompt to Ollama and return the raw response text."""
    use_model = model or OLLAMA_MODEL_DEFAULT
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": use_model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def ollama_analyze_risk(
    title: str, description: str, steps: str, severity: str, model: str = None
) -> Optional[dict]:
    """
    Call Ollama for risk analysis.
    Parses both JSON and plain-English responses.
    Returns None on any failure so callers can fall back to heuristic.
    """
    prompt = f"""You are a QA risk analyst. Analyze this test case.

Title: {title}
Description: {description}
Severity: {severity}

Reply with ONLY these 3 lines (no extra text):
Risk Score: <number 1-10>
Priority: <P1 or P2 or P3>
Explanation: <one sentence>

Where P1=score 8-10, P2=score 5-7, P3=score 1-4"""

    try:
        raw = call_ollama(prompt, model)
        logger.info(f"Ollama raw response for {title[:30]}: {raw[:120]}")

        # Try JSON first
        parsed = extract_json(raw)
        if parsed:
            score    = safe_int(parsed.get("risk_score") or parsed.get("score") or 5, default=5, lo=1, hi=10)
            priority = str(parsed.get("priority") or "").strip()
            if priority not in ("P1", "P2", "P3"):
                priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
            explanation = safe_str(
                parsed.get("explanation") or parsed.get("reason") or
                parsed.get("rationale") or parsed.get("analysis")
            )
            logger.info(f"Ollama JSON risk: {title[:30]} → {priority} ({score})")
            return {"risk_score": score, "priority": priority, "explanation": explanation, "source": "ollama"}

        # Fall back to plain-English parsing
        parsed_text = parse_risk_from_text(raw)
        if parsed_text:
            logger.info(f"Ollama text risk: {title[:30]} → {parsed_text['priority']} ({parsed_text['risk_score']})")
            return {**parsed_text, "source": "ollama"}

    except Exception as e:
        logger.warning(f"Ollama risk failed for '{title[:40]}': {e}")
    return None


def ollama_analyze_automation(
    title: str, description: str, steps: str, model: str = None
) -> Optional[dict]:
    """
    Call Ollama for automation suitability analysis.
    Parses both JSON and plain-English responses.
    Returns None on any failure so callers can fall back to heuristic.
    """
    prompt = f"""You are a QA automation expert. Analyze this test case.

Title: {title}
Description: {description}
Steps: {steps}

Reply with ONLY these 3 lines (no extra text):
Suitability: <Automatable or Partial or Not Suitable>
Confidence: <number 0-100>
Explanation: <one sentence>

Rules:
- Automatable: stable, repeatable, no OTP/Captcha/biometric/physical hardware
- Partial: mostly automatable but has some dynamic or external elements
- Not Suitable: needs human, OTP, Captcha, biometric, voice, physical interaction"""

    try:
        raw = call_ollama(prompt, model)
        logger.info(f"Ollama auto raw for {title[:30]}: {raw[:120]}")

        parsed = extract_json(raw)
        if parsed:
            suitability = str(parsed.get("suitability") or parsed.get("result") or "").strip()
            if suitability not in ("Automatable", "Partial", "Not Suitable"):
                suitability = "Partial"
            confidence  = safe_int(parsed.get("confidence") or parsed.get("score") or 50, default=50, lo=0, hi=100)
            explanation = safe_str(parsed.get("explanation") or parsed.get("reason") or parsed.get("rationale"))
            logger.info(f"Ollama JSON auto: {title[:30]} → {suitability} ({confidence}%)")
            return {"suitability": suitability, "confidence": confidence, "explanation": explanation, "source": "ollama"}

        parsed_text = parse_automation_from_text(raw)
        if parsed_text:
            logger.info(f"Ollama text auto: {title[:30]} → {parsed_text['suitability']} ({parsed_text['confidence']}%)")
            return {**parsed_text, "source": "ollama"}

    except Exception as e:
        logger.warning(f"Ollama automation failed for '{title[:40]}': {e}")
    return None
