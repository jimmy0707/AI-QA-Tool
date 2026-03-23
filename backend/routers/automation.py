"""
routers/automation.py
──────────────────────
POST /api/automation/analyze
GET  /api/download/{session_id}/{report_type}
"""

import io
import uuid
import asyncio
import os
import pandas as pd
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from config import OLLAMA_MODEL_DEFAULT, OUTPUT_DIR, logger
from services.ollama_service    import ollama_analyze_automation
from services.heuristic_service import heuristic_automation
from services.openai_service    import openai_analyze_automation
from services.gemini_service    import gemini_analyze_automation
from services.excel_service     import create_automation_excel

router = APIRouter()


@router.post("/api/automation/analyze")
async def automation_analyze(
    file:         UploadFile    = File(...),
    mode:         str           = Form("offline"),
    openai_key:   Optional[str] = Form(None),
    gemini_key:   Optional[str] = Form(None),
    ollama_model: Optional[str] = Form(None),
):
    contents       = await file.read()
    selected_model = ollama_model or OLLAMA_MODEL_DEFAULT

    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="Excel file is empty.")
    if mode == "online" and not openai_key:
        raise HTTPException(status_code=400, detail="OpenAI API key required for Online mode.")
    if mode == "gemini" and not gemini_key:
        raise HTTPException(status_code=400, detail="Gemini API key required for Gemini mode.")

    rows = [row.to_dict() for _, row in df.iterrows()]
    loop = asyncio.get_event_loop()

    # return_exceptions=True — prevents one failing worker killing the entire batch
    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
        if mode == "online":
            futures = [loop.run_in_executor(pool, openai_analyze_automation, r, openai_key) for r in rows]
        elif mode == "gemini":
            futures = [loop.run_in_executor(pool, gemini_analyze_automation, r, gemini_key) for r in rows]
        else:
            futures = [loop.run_in_executor(pool, _offline_automation, r, selected_model) for r in rows]
        raw_results = await asyncio.gather(*futures, return_exceptions=True)

    # Sanitise — replace any leaked exception with a heuristic result
    results = []
    for i, res in enumerate(raw_results):
        if isinstance(res, Exception):
            rd = rows[i]
            t  = str(rd.get("title") or rd.get("Title") or f"TC-{i+1}")
            logger.warning(f"[Automation] Unhandled exception for '{t[:40]}': {res} — using heuristic")
            fb = heuristic_automation(
                t,
                str(rd.get("description") or rd.get("Description") or ""),
                str(rd.get("steps")       or rd.get("Steps")       or ""),
            )
            fb["mode"] = "heuristic"
            results.append(fb)
        else:
            results.append(res)

    df["Automation Suitability"] = [r["suitability"] for r in results]
    df["Confidence %"]           = [r["confidence"]  for r in results]
    df["AI Explanation"]         = [r["explanation"]  for r in results]
    df["AI Source"]              = [r.get("source") or r.get("mode") or mode for r in results]

    session_id = str(uuid.uuid4())[:8]
    create_automation_excel(df, session_id, mode)

    total        = len(df)
    automatable  = len(df[df["Automation Suitability"] == "Automatable"])
    partial      = len(df[df["Automation Suitability"] == "Partial"])
    not_suitable = len(df[df["Automation Suitability"] == "Not Suitable"])

    return {
        "session_id":          session_id,
        "mode":                mode,
        "total_cases":         total,
        "automatable_count":   automatable,
        "partial_count":       partial,
        "not_suitable_count":  not_suitable,
        "automatable_percent": round(automatable / total * 100) if total else 0,
        "download_url":        f"/api/download/{session_id}/automation",
        "ollama_model":        selected_model,
    }


@router.get("/api/download/{session_id}/{report_type}")
def download_report(session_id: str, report_type: str):
    filename = f"{report_type}_results_{session_id}.xlsx"
    path     = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


# ── Internal dispatcher ───────────────────────────────────────────────────────
def _offline_automation(row: dict, model: str) -> dict:
    from utils.helpers import safe_str
    title       = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps       = safe_str(row.get("steps")       or row.get("Steps")       or row.get("Test Steps"), "")

    result = ollama_analyze_automation(title, description, steps, model)
    if result:
        result["mode"] = "offline"
        return result

    logger.info(f"Using heuristic fallback for: {title[:40]}")
    result = heuristic_automation(title, description, steps)
    result["mode"] = "offline"
    return result
