"""
routers/regression.py
──────────────────────
POST /api/regression/analyze

Accepts an Excel file of test cases, runs AI risk scoring, applies
optional release-aware adjustments, and returns a downloadable Excel report.
"""

import io
import uuid
import asyncio
import pandas as pd
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from config import OLLAMA_MODEL_DEFAULT, logger
from services.ollama_service  import ollama_analyze_risk
from services.heuristic_service import heuristic_risk
from services.openai_service  import openai_analyze_risk
from services.gemini_service  import gemini_analyze_risk
from services.release_service import apply_release_context
from services.excel_service   import create_regression_excel

router = APIRouter()


@router.post("/api/regression/analyze")
async def regression_analyze(
    file:                    UploadFile     = File(...),
    recent_modification_days: Optional[int] = Form(None),
    total_execution_days:    int            = Form(...),
    total_testers:           int            = Form(...),
    cases_per_tester_per_day: int           = Form(...),
    mode:                    str            = Form("offline"),
    openai_key:              Optional[str]  = Form(None),
    gemini_key:              Optional[str]  = Form(None),
    ollama_model:            Optional[str]  = Form(None),
    # ── Release-aware inputs (all optional) ────────────────────────────────
    # Send as comma-separated strings, e.g. "payment,cart,orders"
    changed_modules:         Optional[str]  = Form(None),
    frozen_modules:          Optional[str]  = Form(None),
    current_release_number:  Optional[int]  = Form(None),
):
    contents       = await file.read()
    selected_model = ollama_model or OLLAMA_MODEL_DEFAULT

    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")

    if len(df) > 2000:
        raise HTTPException(status_code=400, detail="Max 2000 test cases allowed.")
    if len(df) == 0:
        raise HTTPException(status_code=400, detail="Excel file is empty.")
    if mode == "online"  and not openai_key:
        raise HTTPException(status_code=400, detail="OpenAI API key required for Online mode.")
    if mode == "gemini"  and not gemini_key:
        raise HTTPException(status_code=400, detail="Gemini API key required for Gemini mode.")

    # Parse comma-separated module lists
    changed_list: list[str] = [m.strip() for m in changed_modules.split(",") if m.strip()] if changed_modules else []
    frozen_list:  list[str] = [m.strip() for m in frozen_modules.split(",")  if m.strip()] if frozen_modules  else []
    release_mode = bool(changed_list or frozen_list or current_release_number)

    if release_mode:
        logger.info(
            f"[Release] Release-aware mode ON — "
            f"changed={changed_list}, frozen={frozen_list}, release={current_release_number}"
        )

    capacity = total_execution_days * total_testers * cases_per_tester_per_day
    rows     = [row.to_dict() for _, row in df.iterrows()]
    loop     = asyncio.get_event_loop()

    # ── AI analysis (parallel workers) ───────────────────────────────────────
    # return_exceptions=True is CRITICAL — without it a single worker raising
    # HTTPException (e.g. Gemini quota on one row) cancels the ENTIRE gather
    # and returns HTTP 401 to the frontend even though all other rows succeeded.
    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
        if mode == "online":
            futures = [loop.run_in_executor(pool, openai_analyze_risk, r, openai_key) for r in rows]
        elif mode == "gemini":
            futures = [loop.run_in_executor(pool, gemini_analyze_risk, r, gemini_key) for r in rows]
        else:
            futures = [loop.run_in_executor(pool, _offline_risk, r, selected_model) for r in rows]
        raw_results = await asyncio.gather(*futures, return_exceptions=True)

    # ── Sanitise — replace any leaked exception with a heuristic result ───────
    results = []
    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            rd = rows[i]
            t  = str(rd.get("title") or rd.get("Title") or f"TC-{i+1}")
            logger.warning(f"[Regression] Unhandled exception for '{t[:40]}': {res} — using heuristic")
            fb = heuristic_risk(
                t,
                str(rd.get("description") or rd.get("Description") or ""),
                str(rd.get("steps")       or rd.get("Steps")       or ""),
                str(rd.get("severity")    or rd.get("Severity")    or ""),
            )
            fb["mode"] = "heuristic"
            results.append(fb)
        else:
            results.append(res)

    # ── Write base AI columns ─────────────────────────────────────────────────
    df["AI Risk Explanation"] = [r["explanation"] for r in results]
    df["AI Source"]           = [r.get("source") or r.get("mode") or mode for r in results]

    if release_mode:
        # ── Apply release-aware adjustments ──────────────────────────────────
        base_scores, adj_scores, adj_reasons, final_priorities = [], [], [], []

        for i, (res, rd) in enumerate(zip(results, rows)):
            base = int(res.get("risk_score") or 5)

            module = str(
                rd.get("module") or rd.get("Module") or rd.get("Module Name") or ""
            ).strip()

            last_release = rd.get("last_executed_release") or rd.get("Last Executed Release")
            try:
                last_release = int(last_release) if last_release is not None else None
            except (ValueError, TypeError):
                last_release = None

            adj = apply_release_context(
                base_score            = base,
                module                = module,
                changed_modules       = changed_list,
                frozen_modules        = frozen_list,
                current_release       = current_release_number,
                last_executed_release = last_release,
            )

            base_scores.append(base)
            adj_scores.append(adj["adjusted_score"])
            final_priorities.append(adj["priority"])
            adj_reasons.append(" | ".join(adj["reasons"]) if adj["reasons"] else "No adjustment")

            if adj["adjustment"] != 0:
                direction = f"+{adj['adjustment']}" if adj["adjustment"] > 0 else str(adj["adjustment"])
                logger.info(
                    f"[Release] '{str(rd.get('title') or rd.get('Title') or f'TC-{i}')[:35]}' "
                    f"base={base} adj={adj['adjusted_score']} ({direction})"
                )

        df["Module"]              = [str(r.get("module") or r.get("Module") or r.get("Module Name") or "—") for r in rows]
        df["Base Risk Score"]     = base_scores
        df["Adjusted Risk Score"] = adj_scores
        df["Priority"]            = final_priorities
        df["Adjustment Reason"]   = adj_reasons
        df["Risk Score"]          = adj_scores   # alias used for sorting

    else:
        df["Risk Score"] = [r["risk_score"] for r in results]
        df["Priority"]   = [r["priority"]   for r in results]

    # ── Sort + execution capacity ─────────────────────────────────────────────
    df_sorted = df.sort_values("Risk Score", ascending=False).reset_index(drop=True)
    df_sorted["Recommended for Execution"] = "No"
    if capacity > 0:
        df_sorted.loc[:capacity - 1, "Recommended for Execution"] = "Yes"

    session_id = str(uuid.uuid4())[:8]
    create_regression_excel(df_sorted, session_id, mode)

    p1                = len(df_sorted[df_sorted["Priority"] == "P1"])
    p2                = len(df_sorted[df_sorted["Priority"] == "P2"])
    p3                = len(df_sorted[df_sorted["Priority"] == "P3"])
    recommended_count = min(capacity, len(df_sorted))
    coverage_pct      = round(recommended_count / len(df_sorted) * 100) if len(df_sorted) > 0 else 0

    response_body = {
        "session_id":        session_id,
        "mode":              mode,
        "total_cases":       len(df_sorted),
        "capacity":          capacity,
        "p1_count":          p1,
        "p2_count":          p2,
        "p3_count":          p3,
        "recommended_count": recommended_count,
        "coverage_percent":  coverage_pct,
        "download_url":      f"/api/download/{session_id}/regression",
        "ollama_model":      selected_model,
        "release_aware":     release_mode,
    }

    if release_mode:
        response_body["release_context"] = {
            "current_release": current_release_number,
            "changed_modules": changed_list,
            "frozen_modules":  frozen_list,
            "boosted_count":   sum(1 for r in adj_reasons if "Changed" in r or "Stale" in r),
            "reduced_count":   sum(1 for r in adj_reasons if "Frozen"  in r),
        }

    return response_body


# ── Internal dispatcher (keeps route handler clean) ──────────────────────────
def _offline_risk(row: dict, model: str) -> dict:
    from utils.helpers import safe_str
    title       = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps       = safe_str(row.get("steps")       or row.get("Steps")       or row.get("Test Steps"), "")
    severity    = safe_str(row.get("severity")     or row.get("Severity"), "")

    result = ollama_analyze_risk(title, description, steps, severity, model)
    if result:
        result["mode"] = "offline"
        return result

    logger.info(f"Using heuristic fallback for: {title[:40]}")
    result = heuristic_risk(title, description, steps, severity)
    result["mode"] = "offline"
    result["model_used"] = "heuristic"
    return result
