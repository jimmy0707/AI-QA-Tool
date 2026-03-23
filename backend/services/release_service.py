"""
services/release_service.py
────────────────────────────
Release-Aware Regression Prioritization.

Pure function — no side effects, no I/O, no imports from other services.
Applied AFTER the AI scores a test case to adjust for release context.
All inputs are optional — fully backward compatible when not supplied.
"""


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
