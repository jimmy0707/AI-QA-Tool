"""
services/heuristic_service.py
─────────────────────────────
LAYER 2 — JSON-driven Keyword Heuristic Engine

Rules live in heuristic_rules.json alongside this file.
Hot-reload: edit the JSON file and the next request picks up the changes
automatically — no server restart needed.
"""

import json
import pathlib

from config import logger
from utils.helpers import safe_str


# ── JSON path ────────────────────────────────────────────────────────────────
_RULES_JSON_PATH = pathlib.Path(__file__).parent.parent / "heuristic_rules.json"

# ── In-memory cache ──────────────────────────────────────────────────────────
# Stores (mtime, risk_rules, auto_rules).
# One os.stat() call per request (~1µs). Zero I/O when file unchanged.
_rules_cache: dict = {"mtime": None, "risk": [], "auto": []}


def _load_rules() -> tuple:
    """
    Return (risk_rules, auto_rules) from heuristic_rules.json.

    HOW HOT-RELOAD WORKS
    ────────────────────
    1. stat() the file mtime — ~1µs, no I/O.
    2. If mtime == cached mtime: return cached tuples immediately.
    3. If mtime changed: re-parse JSON, rebuild tuples, update cache.
    Thread-safe on CPython — GIL protects the dict assignment.

    JSON SCHEMA
    ───────────
    {
      "risk_rules":       [{"keywords": [...], "score_boost": int, "label": str}],
      "automation_rules": [{"keywords": [...], "suitability": str,
                            "confidence": int, "reason": str}]
    }
    """
    try:
        mtime = _RULES_JSON_PATH.stat().st_mtime
    except FileNotFoundError:
        logger.error(f"[Rules] heuristic_rules.json not found at {_RULES_JSON_PATH} — using cached rules")
        return _rules_cache["risk"], _rules_cache["auto"]

    # Cache hit
    if mtime == _rules_cache["mtime"]:
        return _rules_cache["risk"], _rules_cache["auto"]

    # Cache miss — reload
    try:
        raw = json.loads(_RULES_JSON_PATH.read_text(encoding="utf-8"))

        risk_rules = [
            (r["keywords"], r["score_boost"], r["label"])
            for r in raw.get("risk_rules", [])
        ]
        auto_rules = [
            (r["keywords"], r["suitability"], r["confidence"], r["reason"])
            for r in raw.get("automation_rules", [])
        ]

        _rules_cache["mtime"] = mtime
        _rules_cache["risk"]  = risk_rules
        _rules_cache["auto"]  = auto_rules

        total_risk = sum(len(r[0]) for r in risk_rules)
        total_auto = sum(len(r[0]) for r in auto_rules)
        logger.info(
            f"[Rules] Loaded heuristic_rules.json — "
            f"{len(risk_rules)} risk groups ({total_risk} keywords), "
            f"{len(auto_rules)} automation groups ({total_auto} keywords)"
        )
        return risk_rules, auto_rules

    except Exception as e:
        logger.error(f"[Rules] Failed to parse heuristic_rules.json: {e} — using cached rules")
        return _rules_cache["risk"], _rules_cache["auto"]


# Pre-load at startup so the first request has zero cold-start delay
try:
    _load_rules()
except Exception:
    pass


# ── Public functions ─────────────────────────────────────────────────────────

def heuristic_risk(title: str, description: str, steps: str, severity: str) -> dict:
    """
    JSON-driven keyword heuristic for risk scoring.
    Edit heuristic_rules.json to add/remove keywords — no restart needed.
    """
    risk_rules, _ = _load_rules()

    text = (title + " " + description + " " + steps).lower()
    sev  = severity.lower()
    score = 3
    reason_parts = []

    # Severity scoring
    if sev in ("critical", "blocker", "p0"):
        score += 4
        reason_parts.append("critical severity")
    elif sev in ("high", "major", "p1"):
        score += 2
        reason_parts.append("high severity")
    elif sev in ("medium", "moderate", "p2"):
        score += 1

    # Keyword scoring
    matched = False
    for keywords, boost, label in risk_rules:
        if any(k in text for k in keywords):
            score += boost
            reason_parts.append(label)
            matched = True
            break

    if not matched:
        reason_parts.append("general functionality area")

    score = max(1, min(10, score))
    priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
    explanation = f"Risk assessment based on {', '.join(reason_parts)}. Score: {score}/10."
    return {"risk_score": score, "priority": priority, "explanation": explanation, "source": "heuristic"}


def heuristic_automation(title: str, description: str, steps: str) -> dict:
    """
    JSON-driven keyword heuristic for automation suitability.
    Edit heuristic_rules.json to add/remove keywords — no restart needed.
    """
    _, auto_rules = _load_rules()

    text = (title + " " + description + " " + steps).lower()

    for keywords, suitability, confidence, reason in auto_rules:
        if any(k in text for k in keywords):
            return {"suitability": suitability, "confidence": confidence,
                    "explanation": reason, "source": "heuristic"}

    return {
        "suitability": "Partial",
        "confidence":  50,
        "explanation": "Unable to determine automation suitability from content — manual review recommended.",
        "source":      "heuristic",
    }
