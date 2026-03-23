"""
utils/helpers.py
────────────────
Shared utility functions used across all services.
No imports from other project modules — zero circular deps.
"""

import json
import re
from typing import Optional


def safe_str(val, default: str = "AI analysis completed.") -> str:
    """Return a clean string, falling back to default if val is None/empty."""
    if val is None:
        return default
    return str(val).strip() or default


def safe_int(val, default: int = 5, lo: int = 1, hi: int = 10) -> int:
    """Parse val as int, clamped to [lo, hi], returning default on failure."""
    try:
        return max(lo, min(hi, int(val)))
    except Exception:
        return default


def extract_json(raw: str) -> Optional[dict]:
    """Safely extract the first JSON object from any AI response string."""
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception:
        pass
    return None


def parse_risk_from_text(raw: str) -> Optional[dict]:
    """
    Parse risk score, priority and explanation from plain-English AI response.

    Handles responses like:
        Risk Score: Low / Medium / High / 7
        Priority: P1 / High / Critical
        Explanation: ...
    """
    raw_lower = raw.lower()

    # ── Extract risk score ──────────────────────────────────────────────────
    score = None
    m = re.search(r'risk.?score[:\s]+(\d+)', raw_lower)
    if m:
        score = int(m.group(1))
    else:
        if any(w in raw_lower for w in ["risk score: high", "risk: high", "high risk"]):
            score = 8
        elif any(w in raw_lower for w in ["risk score: critical", "critical risk"]):
            score = 9
        elif any(w in raw_lower for w in ["risk score: medium", "risk score: moderate",
                                           "moderate risk", "medium risk"]):
            score = 6
        elif any(w in raw_lower for w in ["risk score: low", "low risk"]):
            score = 3

    # ── Extract priority ────────────────────────────────────────────────────
    priority = None
    m = re.search(r'priority[:\s]+(p[123]|high|medium|low|critical|moderate)', raw_lower)
    if m:
        priority_map = {
            "p1": "P1", "p2": "P2", "p3": "P3",
            "critical": "P1", "high": "P1",
            "medium": "P2", "moderate": "P2",
            "low": "P3",
        }
        priority = priority_map.get(m.group(1))

    # ── Extract explanation ─────────────────────────────────────────────────
    explanation = None
    for pattern in [
        r'explanation[:\s]+(.+)',
        r'risk explanation[:\s]+(.+)',
        r'risk explanation title[:\s]+(.+)',
    ]:
        m = re.search(pattern, raw_lower)
        if m:
            explanation = m.group(1).strip().capitalize()
            break

    if not explanation:
        sentences = [s.strip() for s in raw.split(".") if len(s.strip()) > 20]
        if sentences:
            explanation = sentences[0][:200]

    # ── Derive missing fields ───────────────────────────────────────────────
    if score is None and priority:
        score = {"P1": 8, "P2": 6, "P3": 3}[priority]
    if priority is None and score is not None:
        priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"

    if score is not None and priority is not None and explanation:
        return {
            "risk_score":  max(1, min(10, score)),
            "priority":    priority,
            "explanation": safe_str(explanation),
        }
    return None


def parse_automation_from_text(raw: str) -> Optional[dict]:
    """
    Parse automation suitability from a plain-English AI response.
    """
    raw_lower = raw.lower()

    # ── Extract suitability ─────────────────────────────────────────────────
    suitability = None
    if any(w in raw_lower for w in [
        "not suitable", "not automatable", "cannot be automated", "should not be automated"
    ]):
        suitability = "Not Suitable"
    elif any(w in raw_lower for w in [
        "partially automatable", "partial automation", "partially suitable", "can be partially"
    ]):
        suitability = "Partial"
    elif any(w in raw_lower for w in [
        "fully automatable", "automatable", "can be automated",
        "suitable for automation", "good candidate",
    ]):
        suitability = "Automatable"

    # ── Extract confidence ──────────────────────────────────────────────────
    confidence = None
    m = re.search(r'confidence[:\s]+(\d+)', raw_lower)
    if m:
        confidence = int(m.group(1))
    else:
        if suitability == "Automatable":   confidence = 80
        elif suitability == "Partial":     confidence = 55
        elif suitability == "Not Suitable": confidence = 15

    # ── Extract explanation ─────────────────────────────────────────────────
    explanation = None
    for pattern in [r'explanation[:\s]+(.+)', r'reason[:\s]+(.+)']:
        m = re.search(pattern, raw_lower)
        if m:
            explanation = m.group(1).strip().capitalize()
            break
    if not explanation:
        sentences = [s.strip() for s in raw.split(".") if len(s.strip()) > 20]
        if sentences:
            explanation = sentences[0][:200]

    if suitability and confidence is not None and explanation:
        return {
            "suitability": suitability,
            "confidence":  max(0, min(100, confidence)),
            "explanation": safe_str(explanation),
        }
    return None
