from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pandas as pd
import requests
import json
import os
import io
import uuid
from typing import Optional
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment

app = FastAPI(title="AI QA Decision Intelligence Platform", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3")

# Windows-compatible output directory (same folder as main.py)
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def call_ollama(prompt: str) -> str:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        response.raise_for_status()
        return response.json().get("response", "")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama error: {str(e)}")


def safe_str(val, default="AI analysis completed.") -> str:
    if val is None:
        return default
    return str(val).strip() or default


def safe_int(val, default=5, lo=1, hi=10) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except Exception:
        return default


# ─────────────────────────────────────────────
# AI Risk Analysis
# ─────────────────────────────────────────────
def ai_analyze_risk(row: dict) -> dict:
    title = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    expected = safe_str(row.get("expected") or row.get("Expected") or row.get("Expected Result"), "")
    severity = safe_str(row.get("severity") or row.get("Severity"), "")

    prompt = f"""You are a QA risk analyst. Respond ONLY with a valid JSON object. No extra text.

Test Case Title: {title}
Description: {description}
Steps: {steps}
Expected Result: {expected}
Severity: {severity}

Return ONLY this JSON with no markdown formatting:
{{"risk_score": 7, "priority": "P2", "explanation": "one sentence here"}}

Rules:
- risk_score must be integer 1-10
- priority must be exactly P1, P2, or P3
- P1 = risk_score 8-10, P2 = 5-7, P3 = 1-4"""

    try:
        raw = call_ollama(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
            score = safe_int(
                parsed.get("risk_score") or parsed.get("riskScore") or parsed.get("score") or 5,
                default=5, lo=1, hi=10
            )
            priority = str(parsed.get("priority") or parsed.get("Priority") or "").strip()
            if priority not in ("P1", "P2", "P3"):
                priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
            explanation = safe_str(
                parsed.get("explanation") or parsed.get("risk_explanation") or
                parsed.get("reason") or parsed.get("rationale") or
                parsed.get("analysis") or parsed.get("justification") or parsed.get("summary")
            )
            return {"risk_score": score, "priority": priority, "explanation": explanation}
    except Exception:
        pass

    # Fallback
    t = title.lower()
    if any(k in t for k in ["login", "payment", "auth", "security", "crash", "checkout"]):
        return {"risk_score": 8, "priority": "P1", "explanation": "Critical functionality area detected."}
    elif any(k in t for k in ["search", "filter", "export", "import", "update", "cart"]):
        return {"risk_score": 5, "priority": "P2", "explanation": "Moderate impact functionality."}
    return {"risk_score": 3, "priority": "P3", "explanation": "Low risk functionality."}


# ─────────────────────────────────────────────
# AI Automation Analysis
# ─────────────────────────────────────────────
def ai_analyze_automation(row: dict) -> dict:
    title = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    expected = safe_str(row.get("expected") or row.get("Expected") or row.get("Expected Result"), "")

    prompt = f"""You are a QA automation expert. Respond ONLY with a valid JSON object. No extra text.

Test Case Title: {title}
Description: {description}
Steps: {steps}
Expected Result: {expected}

Return ONLY this JSON with no markdown formatting:
{{"suitability": "Automatable", "confidence": 85, "explanation": "one sentence here"}}

Rules:
- suitability must be exactly: Automatable, Partial, or Not Suitable
- confidence must be integer 0-100
- Automatable = stable, repeatable, no OTP/Captcha (confidence 70-100)
- Partial = some dynamic elements (confidence 40-69)
- Not Suitable = needs human, OTP, Captcha, visual check (confidence 0-39)"""

    try:
        raw = call_ollama(prompt)
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(raw[start:end])
            suitability = str(
                parsed.get("suitability") or parsed.get("automation_suitability") or
                parsed.get("result") or parsed.get("recommendation") or ""
            ).strip()
            if suitability not in ("Automatable", "Partial", "Not Suitable"):
                suitability = "Partial"
            confidence = safe_int(
                parsed.get("confidence") or parsed.get("confidence_percentage") or
                parsed.get("score") or 50,
                default=50, lo=0, hi=100
            )
            explanation = safe_str(
                parsed.get("explanation") or parsed.get("reason") or
                parsed.get("rationale") or parsed.get("analysis") or
                parsed.get("justification") or parsed.get("summary")
            )
            return {"suitability": suitability, "confidence": confidence, "explanation": explanation}
    except Exception:
        pass

    # Fallback
    text = (steps + title).lower()
    if any(k in text for k in ["otp", "captcha", "manual", "visual", "human", "phone"]):
        return {"suitability": "Not Suitable", "confidence": 20, "explanation": "Contains manual or human-dependent steps."}
    elif any(k in text for k in ["api", "database", "verify", "click", "enter", "login", "submit"]):
        return {"suitability": "Automatable", "confidence": 80, "explanation": "Standard repeatable workflow detected."}
    return {"suitability": "Partial", "confidence": 55, "explanation": "Mixed automation feasibility."}


# ─────────────────────────────────────────────
# Excel generators
# ─────────────────────────────────────────────
def create_regression_excel(df: pd.DataFrame, session_id: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Regression Results"

    headers = ["#", "Test Case Title", "Description", "Risk Score", "Priority",
               "AI Risk Explanation", "Recommended for Execution"]
    ws.append(headers)

    hfill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    hfont = Font(color="FFFFFF", bold=True, size=11)
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.fill = hfill
        c.font = hfont
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    priority_colors = {"P1": "FFCCCC", "P2": "FFF2CC", "P3": "D9EAD3"}

    for i, row in df.iterrows():
        title = safe_str(row.get("Title") or row.get("title") or row.get("Test Case Title"), f"TC-{i+1}")
        desc = safe_str(row.get("Description") or row.get("description"), "")
        risk_score = row.get("Risk Score", 5)
        priority = str(row.get("Priority", "P2"))
        explanation = safe_str(row.get("AI Risk Explanation"), "")
        recommended = str(row.get("Recommended for Execution", "No"))

        ws.append([i + 1, title, desc, risk_score, priority, explanation, recommended])
        color = priority_colors.get(priority, "FFFFFF")
        rfill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        for col in range(1, len(headers) + 1):
            c = ws.cell(row=i + 2, column=col)
            c.fill = rfill
            c.alignment = Alignment(wrap_text=True, vertical="top")

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 35
    ws.column_dimensions["C"].width = 40
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 10
    ws.column_dimensions["F"].width = 50
    ws.column_dimensions["G"].width = 25
    ws.row_dimensions[1].height = 35

    ws2 = wb.create_sheet("Summary")
    p1 = len(df[df["Priority"] == "P1"])
    p2 = len(df[df["Priority"] == "P2"])
    p3 = len(df[df["Priority"] == "P3"])
    total = len(df)
    recommended_count = len(df[df["Recommended for Execution"] == "Yes"])

    ws2.append(["AI QA Decision Intelligence - Regression Summary"])
    ws2.merge_cells("A1:C1")
    ws2["A1"].font = Font(bold=True, size=14, color="1E3A5F")
    ws2["A1"].alignment = Alignment(horizontal="center")
    ws2.append([])
    ws2.append(["Metric", "Count", "Percentage"])
    ws2.append(["Total Test Cases", total, "100%"])
    ws2.append(["P1 (Critical)", p1, f"{round(p1/total*100)}%" if total else "0%"])
    ws2.append(["P2 (Moderate)", p2, f"{round(p2/total*100)}%" if total else "0%"])
    ws2.append(["P3 (Low)", p3, f"{round(p3/total*100)}%" if total else "0%"])
    ws2.append(["Recommended for Execution", recommended_count, f"{round(recommended_count/total*100)}%" if total else "0%"])

    sfill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    for col in range(1, 4):
        c = ws2.cell(row=3, column=col)
        c.fill = sfill
        c.font = Font(color="FFFFFF", bold=True)
        c.alignment = Alignment(horizontal="center")
    for col in ["A", "B", "C"]:
        ws2.column_dimensions[col].width = 30

    path = os.path.join(OUTPUT_DIR, f"regression_results_{session_id}.xlsx")
    wb.save(path)
    return path


def create_automation_excel(df: pd.DataFrame, session_id: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Automation Analysis"

    headers = ["#", "Test Case Title", "Description", "Automation Suitability", "Confidence %", "AI Explanation"]
    ws.append(headers)

    hfill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.fill = hfill
        c.font = Font(color="FFFFFF", bold=True, size=11)
        c.alignment = Alignment(horizontal="center", vertical="center")

    suit_colors = {"Automatable": "D9EAD3", "Partial": "FFF2CC", "Not Suitable": "FFCCCC"}

    for i, row in df.iterrows():
        title = safe_str(row.get("Title") or row.get("title") or row.get("Test Case Title"), f"TC-{i+1}")
        desc = safe_str(row.get("Description") or row.get("description"), "")
        suitability = str(row.get("Automation Suitability", "Partial"))
        confidence = row.get("Confidence %", 50)
        explanation = safe_str(row.get("AI Explanation"), "")

        ws.append([i + 1, title, desc, suitability, f"{confidence}%", explanation])
        color = suit_colors.get(suitability, "FFFFFF")
        rfill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        for col in range(1, len(headers) + 1):
            c = ws.cell(row=i + 2, column=col)
            c.fill = rfill
            c.alignment = Alignment(wrap_text=True, vertical="top")

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 35
    ws.column_dimensions["C"].width = 40
    ws.column_dimensions["D"].width = 22
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 55
    ws.row_dimensions[1].height = 35

    ws2 = wb.create_sheet("Summary")
    total = len(df)
    automatable = len(df[df["Automation Suitability"] == "Automatable"])
    partial = len(df[df["Automation Suitability"] == "Partial"])
    not_suitable = len(df[df["Automation Suitability"] == "Not Suitable"])

    ws2.append(["AI QA Decision Intelligence - Automation Summary"])
    ws2.merge_cells("A1:C1")
    ws2["A1"].font = Font(bold=True, size=14, color="1E3A5F")
    ws2["A1"].alignment = Alignment(horizontal="center")
    ws2.append([])
    ws2.append(["Category", "Count", "Percentage"])
    ws2.append(["Total Analyzed", total, "100%"])
    ws2.append(["Automatable", automatable, f"{round(automatable/total*100)}%" if total else "0%"])
    ws2.append(["Partial", partial, f"{round(partial/total*100)}%" if total else "0%"])
    ws2.append(["Not Suitable", not_suitable, f"{round(not_suitable/total*100)}%" if total else "0%"])

    sfill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    for col in range(1, 4):
        c = ws2.cell(row=3, column=col)
        c.fill = sfill
        c.font = Font(color="FFFFFF", bold=True)
        c.alignment = Alignment(horizontal="center")
    for col in ["A", "B", "C"]:
        ws2.column_dimensions[col].width = 28

    path = os.path.join(OUTPUT_DIR, f"automation_results_{session_id}.xlsx")
    wb.save(path)
    return path


# ─────────────────────────────────────────────
# API Routes
# ─────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "AI QA Decision Intelligence Platform Running", "version": "1.0"}


@app.get("/health")
def health():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_status = "connected" if r.ok else "error"
    except Exception:
        ollama_status = "not reachable"
    return {"api": "healthy", "ollama": ollama_status, "model": OLLAMA_MODEL}


@app.post("/api/regression/analyze")
async def regression_analyze(
    file: UploadFile = File(...),
    recent_modification_days: Optional[int] = Form(None),
    total_execution_days: int = Form(...),
    total_testers: int = Form(...),
    cases_per_tester_per_day: int = Form(...)
):
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")

    if len(df) > 2000:
        raise HTTPException(status_code=400, detail="Max 2000 test cases allowed.")
    if len(df) == 0:
        raise HTTPException(status_code=400, detail="Excel file is empty.")

    capacity = total_execution_days * total_testers * cases_per_tester_per_day

    results = []
    for _, row in df.iterrows():
        results.append(ai_analyze_risk(row.to_dict()))

    df["Risk Score"] = [r["risk_score"] for r in results]
    df["Priority"] = [r["priority"] for r in results]
    df["AI Risk Explanation"] = [r["explanation"] for r in results]

    df_sorted = df.sort_values("Risk Score", ascending=False).reset_index(drop=True)
    df_sorted["Recommended for Execution"] = "No"
    if capacity > 0:
        df_sorted.loc[:capacity - 1, "Recommended for Execution"] = "Yes"

    session_id = str(uuid.uuid4())[:8]
    create_regression_excel(df_sorted, session_id)

    p1 = len(df_sorted[df_sorted["Priority"] == "P1"])
    p2 = len(df_sorted[df_sorted["Priority"] == "P2"])
    p3 = len(df_sorted[df_sorted["Priority"] == "P3"])
    recommended_count = min(capacity, len(df_sorted))
    coverage_pct = round(recommended_count / len(df_sorted) * 100) if len(df_sorted) > 0 else 0

    return {
        "session_id": session_id,
        "total_cases": len(df_sorted),
        "capacity": capacity,
        "p1_count": p1,
        "p2_count": p2,
        "p3_count": p3,
        "recommended_count": recommended_count,
        "coverage_percent": coverage_pct,
        "download_url": f"/api/download/{session_id}/regression"
    }


@app.post("/api/automation/analyze")
async def automation_analyze(
    file: UploadFile = File(...)
):
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="Excel file is empty.")

    results = []
    for _, row in df.iterrows():
        results.append(ai_analyze_automation(row.to_dict()))

    df["Automation Suitability"] = [r["suitability"] for r in results]
    df["Confidence %"] = [r["confidence"] for r in results]
    df["AI Explanation"] = [r["explanation"] for r in results]

    session_id = str(uuid.uuid4())[:8]
    create_automation_excel(df, session_id)

    total = len(df)
    automatable = len(df[df["Automation Suitability"] == "Automatable"])
    partial = len(df[df["Automation Suitability"] == "Partial"])
    not_suitable = len(df[df["Automation Suitability"] == "Not Suitable"])

    return {
        "session_id": session_id,
        "total_cases": total,
        "automatable_count": automatable,
        "partial_count": partial,
        "not_suitable_count": not_suitable,
        "automatable_percent": round(automatable / total * 100) if total else 0,
        "download_url": f"/api/download/{session_id}/automation"
    }


@app.get("/api/download/{session_id}/{report_type}")
def download_report(session_id: str, report_type: str):
    filename = f"{report_type}_results_{session_id}.xlsx"
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(
        path=path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )