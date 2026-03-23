"""
services/release_service.py
────────────────────────────
Release-Aware Regression Prioritization.

Two layers of adjustment applied after AI scoring:

  Layer 1 — apply_release_context()
    Pure function (no DB). Adjusts score based on module lists supplied
    by the user at analysis time (changed_modules, frozen_modules, staleness).

  Layer 2 — apply_history_adjustment()
    DB-backed. Adjusts score using actual execution history stored in the DB:
      Rule 1: +2  if same test case FAILED in the previous release
      Rule 2: +2  if test case was NOT executed in any of the last 3 releases
      Rule 3: -3  if module appears in frozen_modules list
    Clamped 1–10. Priority re-derived: P1 ≥ 8, P2 ≥ 5, P3 < 5.
"""

from sqlalchemy.orm import Session


# ── Layer 1: Release-context adjustment (pure, no DB) ────────────────────────

def apply_release_context(
    base_score: int,
    module: str,
    changed_modules: list[str],
    frozen_modules: list[str],
    current_release: int | None,
    last_executed_release: int | None,
) -> dict:
    """
    Adjust a raw AI risk score using release-context signals.

    Returns
    ───────
    {
      "adjusted_score": int,   # clamped 1-10
      "priority":       str,   # P1 / P2 / P3
      "reasons":        list,  # human-readable list of applied rules
      "adjustment":     int,   # net delta (adjusted - base), useful for logging
    }

    Rules (cumulative, applied in order)
    ─────────────────────────────────────
      +3  module is in changed_modules   → active work this release, test it
      -4  module is in frozen_modules    → no changes, deprioritise
      +2  not run for ≥3 releases        → staleness bonus
    """
    score   = base_score
    reasons = []
    mod     = (module or "").strip().lower()

    # Normalise lists to lowercase for case-insensitive matching
    changed_lower = [m.strip().lower() for m in (changed_modules or [])]
    frozen_lower  = [m.strip().lower() for m in (frozen_modules  or [])]

    # Rule 1 — module is changed in this release
    if mod and mod in changed_lower:
        score   += 3
        reasons.append(f"Changed module (+3): '{module}' is active in this release")

    # Rule 2 — module is frozen (no changes expected)
    if mod and mod in frozen_lower:
        score   -= 4
        reasons.append(f"Frozen module (−4): '{module}' has no changes this release")

    # Rule 3 — test has not been run for ≥3 releases (staleness)
    if (
        current_release is not None
        and last_executed_release is not None
        and (current_release - last_executed_release) >= 3
    ):
        gap    = current_release - last_executed_release
        score += 2
        reasons.append(f"Stale test (+2): not run for {gap} releases (last: R{last_executed_release})")

    # Clamp to valid range
    adjusted = max(1, min(10, score))

    # Re-derive priority from adjusted score
    if adjusted >= 8:
        priority = "P1"
    elif adjusted >= 5:
        priority = "P2"
    else:
        priority = "P3"

    return {
        "adjusted_score": adjusted,
        "priority":       priority,
        "reasons":        reasons,
        "adjustment":     adjusted - base_score,
    }


# ── Layer 2: History-based adjustment (DB-backed) ─────────────────────────────

def apply_history_adjustment(
    db: Session,
    test_case_id: int,
    release_id: int,
    module: str,
    base_score: float,
    frozen_modules: list[str] | None = None,
) -> dict:
    """
    Adjust the AI base risk score using historical execution data from the DB.

    Rules
    ─────
      +2  test case status == 'failed' in the immediately preceding release
      +2  test case was not executed in ANY of the last 3 releases
      -3  module is in the frozen_modules list

    Score is clamped between 1 and 10.
    Priority is re-derived: P1 ≥ 8, P2 ≥ 5, P3 < 5.

    Returns
    ───────
    {
      "base_risk_score":     float,   # original AI score, unchanged
      "adjusted_risk_score": float,   # after history rules, clamped 1-10
      "priority":            str,     # P1 / P2 / P3
      "history_reasons":     list,    # human-readable applied rules
      "history_adjustment":  float,   # net delta
    }
    """
    from crud import get_previous_release_execution, get_unexecuted_release_count

    adjustment     = 0.0
    history_reasons = []

    mod           = (module or "").strip().lower()
    frozen_lower  = [m.strip().lower() for m in (frozen_modules or [])]

    # ── Rule 1: Failed in the previous release ────────────────────────────────
    prev_exec = get_previous_release_execution(db, test_case_id, release_id)
    if prev_exec is not None:
        prev_status = (prev_exec.priority or "").strip().upper()
        # We store priority (P1/P2/P3), not pass/fail status in our schema.
        # Check the adj_reason or ai_explanation for "fail" keywords, OR
        # treat a stored risk_score ≥ 8 (P1) as a prior failure signal.
        # Most reliable: check if adj_reason/explanation contains "fail".
        explanation_text = (
            (prev_exec.ai_explanation or "") + " " + (prev_exec.adj_reason or "")
        ).lower()
        was_failed = "fail" in explanation_text or (
            prev_exec.risk_score is not None and prev_exec.risk_score >= 8
        )
        if was_failed:
            adjustment += 2
            history_reasons.append(
                f"Previous release failure (+2): scored {prev_exec.risk_score}/10 "
                f"in release id={prev_exec.release_id}"
            )

    # ── Rule 2: Not executed in last 3 releases ───────────────────────────────
    missed = get_unexecuted_release_count(db, test_case_id, release_id)
    if missed == 3:
        adjustment += 2
        history_reasons.append(
            "Stale test case (+2): not executed in any of the last 3 releases"
        )

    # ── Rule 3: Frozen module ─────────────────────────────────────────────────
    if mod and mod in frozen_lower:
        adjustment -= 3
        history_reasons.append(
            f"Frozen module (−3): '{module}' is marked as frozen in heuristic_rules.json"
        )

    # ── Clamp and derive priority ─────────────────────────────────────────────
    adjusted = round(max(1.0, min(10.0, base_score + adjustment)), 2)

    if adjusted >= 8:
        priority = "P1"
    elif adjusted >= 5:
        priority = "P2"
    else:
        priority = "P3"

    return {
        "base_risk_score":     round(float(base_score), 2),
        "adjusted_risk_score": adjusted,
        "priority":            priority,
        "history_reasons":     history_reasons,
        "history_adjustment":  round(adjustment, 2),
    }