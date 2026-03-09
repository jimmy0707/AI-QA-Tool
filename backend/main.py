from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pandas as pd
import requests
import json
import os
import io
import uuid
import logging
import psutil
import platform
import asyncio
from typing import Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI, RateLimitError, AuthenticationError, APIError
from google import genai
from google.genai import types as genai_types
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from ai_rate_manager import ai_manager

# Windows-safe logging — do NOT use basicConfig as it conflicts with uvicorn on Windows
logger = logging.getLogger("ai-qa-platform")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

app = FastAPI(title="AI QA Decision Intelligence Platform", version="1.0")

# Initialize AI rate manager on startup
@app.on_event("startup")
async def startup():
    await ai_manager.initialize()
    logger.info("AI Rate Manager ready")

# IMPROVEMENT 5: CORS origins from environment (secure)
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS = ["*"] if _raw_origins == "*" else [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL_DEFAULT = os.getenv("OLLAMA_MODEL", "phi3")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─────────────────────────────────────────────
# Ollama Model Registry
# ─────────────────────────────────────────────
OLLAMA_MODELS = {
    "tinyllama": {
        "label": "TinyLlama",
        "size": "637 MB",
        "ram_required": 2,
        "speed": "Instant",
        "quality": "Good",
        "best_for": "Very slow / old PCs (under 4GB RAM)",
        "tier": 1,
    },
    "phi3": {
        "label": "Phi-3 (Default)",
        "size": "2.2 GB",
        "ram_required": 4,
        "speed": "Fast",
        "quality": "Very Good",
        "best_for": "Most laptops and PCs (4-8GB RAM)",
        "tier": 2,
    },
    "mistral": {
        "label": "Mistral 7B",
        "size": "4.1 GB",
        "ram_required": 8,
        "speed": "Moderate",
        "quality": "Excellent",
        "best_for": "Mid-range PC (8-16GB RAM)",
        "tier": 3,
    },
    "llama3": {
        "label": "LLaMA 3 8B",
        "size": "4.7 GB",
        "ram_required": 8,
        "speed": "Moderate",
        "quality": "Best",
        "best_for": "Fast PC (16GB+ RAM)",
        "tier": 4,
    },
}

def get_hardware_info() -> dict:
    try:
        ram_gb = round(psutil.virtual_memory().total / (1024 ** 3))
        cpu_cores = psutil.cpu_count(logical=False) or psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()
        cpu_mhz = round(cpu_freq.current) if cpu_freq else 0
        return {"ram_gb": ram_gb, "cpu_cores": cpu_cores, "cpu_mhz": cpu_mhz, "platform": platform.processor() or platform.machine()}
    except Exception:
        return {"ram_gb": 4, "cpu_cores": 2, "cpu_mhz": 0, "platform": "unknown"}

def suggest_model(ram_gb: int) -> str:
    if ram_gb >= 16:
        return "llama3"
    elif ram_gb >= 8:
        return "mistral"
    elif ram_gb >= 4:
        return "phi3"
    else:
        return "tinyllama"

def get_installed_models() -> list:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.ok:
            models = r.json().get("models", [])
            return [m["name"].split(":")[0] for m in models]
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def safe_str(val, default="AI analysis completed.") -> str:
    if val is None:
        return default
    return str(val).strip() or default

def safe_int(val, default=5, lo=1, hi=10) -> int:
    try:
        return max(lo, min(hi, int(val)))
    except Exception:
        return default

def extract_json(raw: str) -> Optional[dict]:
    """Safely extract JSON from any AI response."""
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(raw[start:end])
    except Exception:
        pass
    return None

def parse_risk_from_text(raw: str) -> Optional[dict]:
    """
    Parse risk score, priority and explanation from plain English AI response.
    Handles responses like:
      Risk Score: Low / Medium / High / 7
      Priority: P1 / High / Critical
      Explanation: ...
    """
    import re
    raw_lower = raw.lower()

    # ── Extract risk score ──
    score = None
    # Try numeric first: "Risk Score: 7" or "score: 8/10"
    m = re.search(r'risk.?score[:\s]+(\d+)', raw_lower)
    if m:
        score = int(m.group(1))
    else:
        # Try text-based score
        if any(w in raw_lower for w in ["risk score: high", "risk: high", "high risk"]):
            score = 8
        elif any(w in raw_lower for w in ["risk score: critical", "critical risk"]):
            score = 9
        elif any(w in raw_lower for w in ["risk score: medium", "risk score: moderate", "moderate risk", "medium risk"]):
            score = 6
        elif any(w in raw_lower for w in ["risk score: low", "low risk"]):
            score = 3

    # ── Extract priority ──
    priority = None
    m = re.search(r'priority[:\s]+(p[123]|high|medium|low|critical|moderate)', raw_lower)
    if m:
        val = m.group(1)
        priority_map = {"p1": "P1", "p2": "P2", "p3": "P3",
                        "critical": "P1", "high": "P1",
                        "medium": "P2", "moderate": "P2",
                        "low": "P3"}
        priority = priority_map.get(val, None)

    # ── Extract explanation ──
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

    # If no explanation found, grab first meaningful sentence
    if not explanation:
        sentences = [s.strip() for s in raw.split(".") if len(s.strip()) > 20]
        if sentences:
            explanation = sentences[0][:200]

    # ── Derive missing fields ──
    if score is None and priority:
        score = {"P1": 8, "P2": 6, "P3": 3}[priority]
    if priority is None and score is not None:
        priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"

    if score is not None and priority is not None and explanation:
        return {
            "risk_score": max(1, min(10, score)),
            "priority": priority,
            "explanation": safe_str(explanation),
        }
    return None


def parse_automation_from_text(raw: str) -> Optional[dict]:
    """
    Parse automation suitability from plain English AI response.
    """
    import re
    raw_lower = raw.lower()

    # ── Extract suitability ──
    suitability = None
    if any(w in raw_lower for w in ["not suitable", "not automatable", "cannot be automated", "should not be automated"]):
        suitability = "Not Suitable"
    elif any(w in raw_lower for w in ["partially automatable", "partial automation", "partially suitable", "can be partially"]):
        suitability = "Partial"
    elif any(w in raw_lower for w in ["fully automatable", "automatable", "can be automated", "suitable for automation", "good candidate"]):
        suitability = "Automatable"

    # ── Extract confidence ──
    confidence = None
    m = re.search(r'confidence[:\s]+(\d+)', raw_lower)
    if m:
        confidence = int(m.group(1))
    else:
        if suitability == "Automatable":
            confidence = 80
        elif suitability == "Partial":
            confidence = 55
        elif suitability == "Not Suitable":
            confidence = 15

    # ── Extract explanation ──
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
            "confidence": max(0, min(100, confidence)),
            "explanation": safe_str(explanation),
        }
    return None


# ─────────────────────────────────────────────
# LAYER 1 — Ollama AI (handles ANY test case)
# ─────────────────────────────────────────────
def call_ollama(prompt: str, model: str = None) -> str:
    use_model = model or OLLAMA_MODEL_DEFAULT
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": use_model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def ollama_analyze_risk(title: str, description: str, steps: str, severity: str, model: str = None) -> Optional[dict]:
    """Call Ollama — parses both JSON and plain English responses."""
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
            score = safe_int(parsed.get("risk_score") or parsed.get("score") or 5, default=5, lo=1, hi=10)
            priority = str(parsed.get("priority") or "").strip()
            if priority not in ("P1", "P2", "P3"):
                priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
            explanation = safe_str(
                parsed.get("explanation") or parsed.get("reason") or
                parsed.get("rationale") or parsed.get("analysis")
            )
            logger.info(f"Ollama JSON risk: {title[:30]} → {priority} ({score})")
            return {"risk_score": score, "priority": priority, "explanation": explanation, "source": "ollama"}

        # Try plain English parsing (e.g. "Risk Score: Low\nPriority: Medium\nExplanation: ...")
        parsed_text = parse_risk_from_text(raw)
        if parsed_text:
            logger.info(f"Ollama text risk: {title[:30]} → {parsed_text['priority']} ({parsed_text['risk_score']})")
            return {**parsed_text, "source": "ollama"}

    except Exception as e:
        logger.warning(f"Ollama risk failed for '{title[:40]}': {e}")
    return None


def ollama_analyze_automation(title: str, description: str, steps: str, model: str = None) -> Optional[dict]:
    """Call Ollama — parses both JSON and plain English automation responses."""
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

        # Try JSON first
        parsed = extract_json(raw)
        if parsed:
            suitability = str(parsed.get("suitability") or parsed.get("result") or "").strip()
            if suitability not in ("Automatable", "Partial", "Not Suitable"):
                suitability = "Partial"
            confidence = safe_int(parsed.get("confidence") or parsed.get("score") or 50, default=50, lo=0, hi=100)
            explanation = safe_str(parsed.get("explanation") or parsed.get("reason") or parsed.get("rationale"))
            logger.info(f"Ollama JSON auto: {title[:30]} → {suitability} ({confidence}%)")
            return {"suitability": suitability, "confidence": confidence, "explanation": explanation, "source": "ollama"}

        # Try plain English parsing
        parsed_text = parse_automation_from_text(raw)
        if parsed_text:
            logger.info(f"Ollama text auto: {title[:30]} → {parsed_text['suitability']} ({parsed_text['confidence']}%)")
            return {**parsed_text, "source": "ollama"}

    except Exception as e:
        logger.warning(f"Ollama automation failed for '{title[:40]}': {e}")
    return None


# ─────────────────────────────────────────────
# LAYER 2 — Extended Keyword Heuristic
# Covers 100+ QA domain keywords across all industries
# ─────────────────────────────────────────────
RISK_RULES = [
    # (keywords, score_boost, label)
    # P1 Critical
    (["payment", "checkout", "transaction", "refund", "billing", "invoice", "stripe", "paypal"], 5, "payment processing"),
    (["login", "logout", "auth", "authentication", "authorize", "sso", "oauth", "jwt", "session", "token"], 5, "authentication/authorization"),
    (["password", "credentials", "encrypt", "decrypt", "ssl", "tls", "certificate", "https"], 5, "security/encryption"),
    (["crash", "exception", "error", "failure", "corrupt", "data loss", "unresponsive", "freeze"], 5, "system stability"),
    (["biometric", "fingerprint", "face id", "face recognition", "iris", "retina"], 5, "biometric security"),
    (["blockchain", "smart contract", "wallet", "crypto", "nft", "defi", "web3"], 5, "blockchain/crypto"),
    (["gdpr", "hipaa", "pci", "compliance", "regulation", "audit", "privacy"], 5, "regulatory compliance"),
    (["database", "sql", "migration", "backup", "restore", "data integrity"], 4, "data integrity"),
    (["api", "endpoint", "rest", "graphql", "webhook", "integration", "microservice"], 4, "API/integration"),
    (["otp", "two factor", "2fa", "mfa", "verification code", "sms code"], 4, "multi-factor auth"),
    # P2 Moderate
    (["search", "filter", "sort", "pagination", "query"], 2, "search/filter functionality"),
    (["upload", "download", "import", "export", "file", "attachment", "document"], 2, "file management"),
    (["notification", "email", "push", "alert", "reminder", "sms"], 2, "notification system"),
    (["cart", "wishlist", "order", "product", "inventory", "stock"], 2, "e-commerce workflow"),
    (["profile", "account", "settings", "preferences", "dashboard"], 2, "user management"),
    (["report", "analytics", "chart", "graph", "metrics", "kpi", "dashboard"], 2, "reporting/analytics"),
    (["mobile", "ios", "android", "responsive", "tablet", "device"], 2, "mobile/responsive"),
    (["performance", "load", "stress", "latency", "throughput", "speed"], 2, "performance testing"),
    (["iot", "sensor", "device", "hardware", "embedded", "firmware"], 3, "IoT/hardware"),
    (["ai", "ml", "model", "prediction", "recommendation", "nlp"], 2, "AI/ML feature"),
    (["ar", "vr", "augmented", "virtual reality", "3d", "spatial"], 2, "AR/VR feature"),
    (["accessibility", "wcag", "aria", "screen reader", "keyboard nav"], 2, "accessibility"),
    (["chat", "messaging", "realtime", "websocket", "live", "streaming"], 2, "real-time feature"),
    (["social", "share", "like", "comment", "follow", "feed"], 1, "social feature"),
    # P3 Low
    (["ui", "layout", "color", "font", "icon", "tooltip", "style", "css"], 0, "UI/styling"),
    (["spelling", "typo", "grammar", "text", "label", "placeholder"], 0, "content/copy"),
]

AUTOMATION_RULES = [
    # (keywords, suitability, confidence, reason)
    # Not Suitable
    (["otp", "one time password", "verification code", "sms code"], "Not Suitable", 10, "Requires real OTP which cannot be automated"),
    (["captcha", "recaptcha", "human verification", "robot check"], "Not Suitable", 10, "CAPTCHA requires human interaction"),
    (["biometric", "fingerprint", "face id", "face recognition", "iris scan"], "Not Suitable", 10, "Biometric requires physical hardware"),
    (["physical", "hardware", "device", "iot sensor", "barcode scan", "qr scan"], "Not Suitable", 15, "Requires physical device interaction"),
    (["visual inspection", "visual check", "manual review", "human review", "look and feel"], "Not Suitable", 20, "Requires human visual judgment"),
    (["voice", "speech", "audio", "sound", "microphone", "speaker"], "Not Suitable", 20, "Requires audio hardware interaction"),
    (["ar", "vr", "augmented reality", "virtual reality", "spatial"], "Not Suitable", 25, "AR/VR requires specialized hardware"),
    (["usability", "ux review", "user experience review", "user interview"], "Not Suitable", 15, "Usability requires human evaluation"),
    # Partial
    (["email notification", "push notification", "sms notification"], "Partial", 45, "Notification delivery needs external verification"),
    (["third party", "external service", "payment gateway", "external api"], "Partial", 50, "External dependencies may affect reliability"),
    (["dynamic data", "random data", "real-time data", "live data"], "Partial", 50, "Dynamic data makes assertions challenging"),
    (["drag and drop", "file upload", "file download", "file picker"], "Partial", 55, "File interactions have partial automation support"),
    (["mobile gesture", "swipe", "pinch", "scroll", "touch"], "Partial", 55, "Mobile gestures have partial automation support"),
    (["blockchain", "smart contract", "crypto", "wallet"], "Partial", 40, "Blockchain interactions need specialized frameworks"),
    (["pdf", "excel", "word", "document generation", "report generation"], "Partial", 60, "Document generation needs content validation"),
    (["performance", "load test", "stress test", "benchmark"], "Partial", 65, "Performance testing needs specialized tools"),
    # Automatable
    (["api", "rest", "graphql", "endpoint", "http", "json", "xml"], "Automatable", 90, "API testing is highly automatable"),
    (["database", "sql", "db query", "data validation", "db record"], "Automatable", 90, "Database validation is highly automatable"),
    (["login", "logout", "register", "signup", "forgot password"], "Automatable", 85, "Authentication flows are standard automation candidates"),
    (["form", "input", "field", "submit", "button", "checkbox", "dropdown"], "Automatable", 85, "Form interactions are easily automatable"),
    (["search", "filter", "sort", "pagination"], "Automatable", 80, "Search/filter functionality is automatable"),
    (["navigation", "menu", "link", "redirect", "routing"], "Automatable", 85, "Navigation testing is automatable"),
    (["crud", "create", "read", "update", "delete"], "Automatable", 85, "CRUD operations are standard automation candidates"),
    (["validation", "error message", "alert", "toast", "warning"], "Automatable", 80, "Validation messages are automatable"),
]


def heuristic_risk(title: str, description: str, steps: str, severity: str) -> dict:
    """Extended keyword heuristic covering 100+ QA domains."""
    text = (title + " " + description + " " + steps).lower()
    sev = severity.lower()
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
    for keywords, boost, label in RISK_RULES:
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
    """Extended keyword heuristic covering 100+ automation patterns."""
    text = (title + " " + description + " " + steps).lower()

    for keywords, suitability, confidence, reason in AUTOMATION_RULES:
        if any(k in text for k in keywords):
            return {"suitability": suitability, "confidence": confidence, "explanation": reason, "source": "heuristic"}

    return {
        "suitability": "Partial",
        "confidence": 50,
        "explanation": "Unable to determine automation suitability from content — manual review recommended.",
        "source": "heuristic"
    }


# ─────────────────────────────────────────────
# LAYER 3 — Smart Dispatcher
# Tries Ollama first → falls back to heuristic
# ─────────────────────────────────────────────
def offline_analyze_risk(row: dict, model: str = None) -> dict:
    title = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    severity = safe_str(row.get("severity") or row.get("Severity"), "")

    # Try Ollama AI first — handles any test case
    result = ollama_analyze_risk(title, description, steps, severity, model)
    if result:
        result["mode"] = "offline"
        return result

    # Fallback to extended heuristic
    logger.info(f"Using heuristic fallback for: {title[:40]}")
    result = heuristic_risk(title, description, steps, severity)
    result["mode"] = "offline"
    result["model_used"] = "heuristic"
    return result


def offline_analyze_automation(row: dict, model: str = None) -> dict:
    title = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")

    # Try Ollama AI first — handles any test case
    result = ollama_analyze_automation(title, description, steps, model)
    if result:
        result["mode"] = "offline"
        return result

    # Fallback to extended heuristic
    logger.info(f"Using heuristic fallback for: {title[:40]}")
    result = heuristic_automation(title, description, steps)
    result["mode"] = "offline"
    return result


# ─────────────────────────────────────────────
# ONLINE MODE — OpenAI (SDK, gpt-4o-mini, strict JSON)
# IMPROVEMENTS: 1 (SDK + model), 4 (strict JSON), 6 (helpers)
# ─────────────────────────────────────────────

# IMPROVEMENT 6: shared field extractors
def _extract_risk_fields(row: dict):
    title = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    severity = safe_str(row.get("severity") or row.get("Severity"), "")
    return title, description, steps, severity

def _extract_auto_fields(row: dict):
    title = safe_str(row.get("title") or row.get("Title") or row.get("Test Case Title"), "Untitled")
    description = safe_str(row.get("description") or row.get("Description") or row.get("Test Description"), "")
    steps = safe_str(row.get("steps") or row.get("Steps") or row.get("Test Steps"), "")
    return title, description, steps

# IMPROVEMENT 1: Official OpenAI SDK, gpt-4o-mini, strict JSON
def call_openai_sdk(prompt: str, api_key: str, system: str) -> str:
    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=200,
    )
    return response.choices[0].message.content


def openai_analyze_risk(row: dict, api_key: str) -> dict:
    title, description, steps, severity = _extract_risk_fields(row)
    system = (
        "You are a senior QA risk analyst. Respond with valid JSON only. "
        "Keys: risk_score (int 1-10), priority (P1|P2|P3), explanation (string). "
        "P1=8-10 critical, P2=5-7 moderate, P3=1-4 low."
    )
    prompt = f"Title: {title}\nDescription: {description}\nSteps: {steps}\nSeverity: {severity}"
    try:
        # Pass through rate manager — handles caching, queuing, retry
        fn  = lambda: call_openai_sdk(prompt, api_key, system)
        raw = asyncio.get_event_loop().run_until_complete(
            ai_manager.call("openai", prompt, fn)
        )
        parsed = json.loads(raw)
        score = safe_int(parsed.get("risk_score") or 5, default=5, lo=1, hi=10)
        priority = str(parsed.get("priority") or "").strip()
        if priority not in ("P1", "P2", "P3"):
            priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        return {"risk_score": score, "priority": priority, "explanation": explanation, "mode": "online", "source": "openai"}
    except RateLimitError:
        logger.warning(f"OpenAI rate limited — falling back to Ollama for: {title[:40]}")
        result = ollama_analyze_risk(title, description, steps, severity) or heuristic_risk(title, description, steps, severity)
        result["mode"] = "online-fallback"
        return result
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.")
    except (APIError, Exception) as e:
        logger.warning(f"OpenAI error — falling back to Ollama: {e}")
        result = ollama_analyze_risk(title, description, steps, severity) or heuristic_risk(title, description, steps, severity)
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
        raw = call_openai_sdk(prompt, api_key, system)
        parsed = json.loads(raw)
        suitability = str(parsed.get("suitability") or "").strip()
        if suitability not in ("Automatable", "Partial", "Not Suitable"):
            suitability = "Partial"
        confidence = safe_int(parsed.get("confidence") or 50, default=50, lo=0, hi=100)
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        return {"suitability": suitability, "confidence": confidence, "explanation": explanation, "mode": "online", "source": "openai"}
    except RateLimitError:
        logger.warning(f"OpenAI rate limited — falling back to Ollama for: {title[:40]}")
        result = ollama_analyze_automation(title, description, steps) or heuristic_automation(title, description, steps)
        result["mode"] = "online-fallback"
        return result
    except AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.")
    except (APIError, Exception) as e:
        raise HTTPException(status_code=502, detail=f"OpenAI error: {str(e)}")


# ─────────────────────────────────────────────
# GEMINI MODE — Google Gemini AI
# ─────────────────────────────────────────────

def call_gemini(prompt: str, api_key: str) -> str:
    """Call Gemini 1.5 Flash using new google-genai SDK."""
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=200,
            response_mime_type="application/json",
        ),
    )
    return response.text


def gemini_analyze_risk(row: dict, api_key: str) -> dict:
    """Analyze test case risk using Gemini — goes through rate manager."""
    title, description, steps, severity = _extract_risk_fields(row)
    prompt = (
        "You are a senior QA risk analyst. Respond with valid JSON only.\n"
        f"Title: {title}\nDescription: {description}\nSteps: {steps}\nSeverity: {severity}\n\n"
        "Return exactly this JSON structure:\n"
        '{"risk_score": 7, "priority": "P2", "explanation": "one professional sentence"}\n'
        "Rules: risk_score integer 1-10, priority P1 (8-10) P2 (5-7) P3 (1-4)."
    )
    try:
        fn  = lambda: call_gemini(prompt, api_key)
        raw = asyncio.get_event_loop().run_until_complete(
            ai_manager.call("gemini", prompt, fn)
        )
        parsed = json.loads(raw)
        score = safe_int(parsed.get("risk_score") or 5, default=5, lo=1, hi=10)
        priority = str(parsed.get("priority") or "").strip()
        if priority not in ("P1", "P2", "P3"):
            priority = "P1" if score >= 8 else "P2" if score >= 5 else "P3"
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        logger.info(f"Gemini risk: {title[:30]} → {priority} ({score})")
        return {"risk_score": score, "priority": priority, "explanation": explanation, "mode": "gemini", "source": "gemini"}
    except Exception as e:
        err = str(e).lower()
        if "api_key" in err or "invalid" in err or "permission" in err:
            raise HTTPException(status_code=401, detail="Invalid Gemini API key.")
        logger.warning(f"Gemini error — falling back to Ollama: {e}")
        result = ollama_analyze_risk(title, description, steps, severity) or heuristic_risk(title, description, steps, severity)
        result["mode"] = "gemini-fallback"
        return result


def gemini_analyze_automation(row: dict, api_key: str) -> dict:
    """Analyze automation suitability using Gemini — same output format as OpenAI/Ollama."""
    title, description, steps = _extract_auto_fields(row)

    prompt = (
        "You are a senior QA automation architect. Respond with valid JSON only.\n"
        f"Title: {title}\nDescription: {description}\nSteps: {steps}\n\n"
        "Return exactly this JSON structure:\n"
        '{"suitability": "Automatable", "confidence": 85, "explanation": "one professional sentence"}\n'
        "Rules: suitability must be exactly Automatable, Partial, or Not Suitable. "
        "Automatable=stable repeatable no OTP/Captcha. "
        "Partial=some dynamic or external dependencies. "
        "Not Suitable=needs human judgment, OTP, Captcha, biometric, or physical hardware."
    )

    try:
        raw = call_gemini(prompt, api_key)
        parsed = json.loads(raw)
        suitability = str(parsed.get("suitability") or "").strip()
        if suitability not in ("Automatable", "Partial", "Not Suitable"):
            suitability = "Partial"
        confidence = safe_int(parsed.get("confidence") or 50, default=50, lo=0, hi=100)
        explanation = safe_str(parsed.get("explanation") or parsed.get("reason"))
        logger.info(f"Gemini automation: {title[:30]} → {suitability} ({confidence}%)")
        return {"suitability": suitability, "confidence": confidence, "explanation": explanation, "mode": "gemini", "source": "gemini"}

    except Exception as e:
        err = str(e).lower()
        if "api_key" in err or "invalid" in err or "permission" in err:
            raise HTTPException(status_code=401, detail="Invalid Gemini API key.")
        if "quota" in err or "rate" in err or "429" in err:
            logger.warning(f"Gemini quota exceeded — falling back to Ollama for: {title[:40]}")
        else:
            logger.warning(f"Gemini error ({e}) — falling back to Ollama for: {title[:40]}")

        result = ollama_analyze_automation(title, description, steps) or heuristic_automation(title, description, steps)
        result["mode"] = "gemini-fallback"
        return result


# ─────────────────────────────────────────────
# Excel generators
# ─────────────────────────────────────────────
def create_regression_excel(df: pd.DataFrame, session_id: str, mode: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Regression Results"
    headers = ["#", "Test Case Title", "Description", "Risk Score", "Priority",
               "AI Risk Explanation", "Recommended for Execution", "AI Mode"]
    ws.append(headers)

    hfill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
    for col in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col)
        c.fill = hfill
        c.font = Font(color="FFFFFF", bold=True, size=11)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    priority_colors = {"P1": "FFCCCC", "P2": "FFF2CC", "P3": "D9EAD3"}
    for i, row in df.iterrows():
        title = safe_str(row.get("Title") or row.get("title") or row.get("Test Case Title"), f"TC-{i+1}")
        desc = safe_str(row.get("Description") or row.get("description"), "")
        risk_score = row.get("Risk Score", 5)
        priority = str(row.get("Priority", "P2"))
        explanation = safe_str(row.get("AI Risk Explanation"), "")
        recommended = str(row.get("Recommended for Execution", "No"))
        ai_mode = str(row.get("AI Mode", mode)).upper()

        ws.append([i + 1, title, desc, risk_score, priority, explanation, recommended, ai_mode])
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
    ws.column_dimensions["H"].width = 16
    ws.row_dimensions[1].height = 35

    ws2 = wb.create_sheet("Summary")
    p1 = len(df[df["Priority"] == "P1"])
    p2 = len(df[df["Priority"] == "P2"])
    p3 = len(df[df["Priority"] == "P3"])
    total = len(df)
    rec = len(df[df["Recommended for Execution"] == "Yes"])
    ws2.append([f"AI QA Decision Intelligence - Regression Summary ({mode.upper()} MODE)"])
    ws2.merge_cells("A1:C1")
    ws2["A1"].font = Font(bold=True, size=14, color="1E3A5F")
    ws2["A1"].alignment = Alignment(horizontal="center")
    ws2.append([])
    ws2.append(["Metric", "Count", "Percentage"])
    ws2.append(["Total Test Cases", total, "100%"])
    ws2.append(["P1 (Critical)", p1, f"{round(p1/total*100)}%" if total else "0%"])
    ws2.append(["P2 (Moderate)", p2, f"{round(p2/total*100)}%" if total else "0%"])
    ws2.append(["P3 (Low)", p3, f"{round(p3/total*100)}%" if total else "0%"])
    ws2.append(["Recommended for Execution", rec, f"{round(rec/total*100)}%" if total else "0%"])
    ws2.append(["AI Mode", mode.upper(), ""])
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


def create_automation_excel(df: pd.DataFrame, session_id: str, mode: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Automation Analysis"
    headers = ["#", "Test Case Title", "Description", "Automation Suitability",
               "Confidence %", "AI Explanation", "AI Mode"]
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
        ai_mode = str(row.get("AI Mode", mode)).upper()

        ws.append([i + 1, title, desc, suitability, f"{confidence}%", explanation, ai_mode])
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
    ws.column_dimensions["G"].width = 16
    ws.row_dimensions[1].height = 35

    ws2 = wb.create_sheet("Summary")
    total = len(df)
    automatable = len(df[df["Automation Suitability"] == "Automatable"])
    partial = len(df[df["Automation Suitability"] == "Partial"])
    not_suitable = len(df[df["Automation Suitability"] == "Not Suitable"])
    ws2.append([f"AI QA Decision Intelligence - Automation Summary ({mode.upper()} MODE)"])
    ws2.merge_cells("A1:C1")
    ws2["A1"].font = Font(bold=True, size=14, color="1E3A5F")
    ws2["A1"].alignment = Alignment(horizontal="center")
    ws2.append([])
    ws2.append(["Category", "Count", "Percentage"])
    ws2.append(["Total Analyzed", total, "100%"])
    ws2.append(["Automatable", automatable, f"{round(automatable/total*100)}%" if total else "0%"])
    ws2.append(["Partial", partial, f"{round(partial/total*100)}%" if total else "0%"])
    ws2.append(["Not Suitable", not_suitable, f"{round(not_suitable/total*100)}%" if total else "0%"])
    ws2.append(["AI Mode", mode.upper(), ""])
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
    # IMPROVEMENT 2 (Bug fix): was using undefined OLLAMA_MODEL, now uses OLLAMA_MODEL_DEFAULT
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_status = "connected" if r.ok else "error"
    except Exception:
        ollama_status = "not reachable"
    return {"api": "healthy", "ollama": ollama_status, "model": OLLAMA_MODEL_DEFAULT}


@app.get("/api/test")
def test():
    return {"status": "backend working", "output_dir": OUTPUT_DIR}


@app.get("/api/rate-stats")
def rate_stats():
    """Live monitoring — token bucket status, cache hit rate, queue size."""
    return ai_manager.get_stats()


@app.get("/api/ai-status")
def ai_status():
    """Returns real-time rate limit usage, cache stats and queue depth."""
    return ai_manager.get_status()


@app.post("/api/validate-key")
async def validate_key(data: dict):
    """
    Auto-detect key type from format and validate.
    OpenAI keys start with: sk-
    Gemini keys start with: AIza
    """
    api_key = data.get("api_key", "").strip()

    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    # ── Auto-detect key type ──
    if api_key.startswith("sk-"):
        key_type = "openai"
    elif api_key.startswith("AIza"):
        key_type = "gemini"
    else:
        return {
            "valid": False,
            "key_type": "unknown",
            "message": "Cannot identify key type. OpenAI keys start with 'sk-', Gemini keys start with 'AIza'."
        }

    # ── Validate OpenAI ──
    if key_type == "openai":
        try:
            client = OpenAI(api_key=api_key, timeout=10.0, max_retries=0)
            client.models.list()
            return {"valid": True, "key_type": "openai", "message": "OpenAI API key is valid ✓", "mode": "online"}
        except AuthenticationError:
            return {"valid": False, "key_type": "openai", "message": "Invalid OpenAI API key."}
        except RateLimitError:
            return {"valid": True, "key_type": "openai", "message": "OpenAI key valid but quota exceeded ⚠", "mode": "online"}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"OpenAI connection error: {str(e)}")

    # ── Validate Gemini ──
    if key_type == "gemini":
        try:
            client = genai.Client(api_key=api_key)
            models = list(client.models.list())
            if not models:
                raise HTTPException(status_code=502, detail="Could not reach Gemini API.")
            return {"valid": True, "key_type": "gemini", "message": "Gemini API key is valid ✓", "mode": "gemini"}
        except Exception as e:
            err = str(e).lower()
            if "api_key" in err or "invalid" in err or "permission" in err or "403" in err:
                return {"valid": False, "key_type": "gemini", "message": "Invalid Gemini API key."}
            raise HTTPException(status_code=502, detail=f"Gemini connection error: {str(e)}")


# Keep old endpoints as aliases so existing frontend calls don't break
@app.post("/api/validate-openai-key")
async def validate_openai_key_alias(data: dict):
    return await validate_key(data)

@app.post("/api/validate-gemini-key")
async def validate_gemini_key_alias(data: dict):
    return await validate_key(data)





@app.get("/api/hardware")
def hardware_info():
    """Return hardware specs and suggested model."""
    hw = get_hardware_info()
    suggested = suggest_model(hw["ram_gb"])
    installed = get_installed_models()
    models_info = []
    for key, info in OLLAMA_MODELS.items():
        models_info.append({
            "name": key,
            "label": info["label"],
            "size": info["size"],
            "ram_required": info["ram_required"],
            "speed": info["speed"],
            "quality": info["quality"],
            "best_for": info["best_for"],
            "tier": info["tier"],
            "is_suggested": key == suggested,
            "is_installed": key in installed,
        })
    return {
        "hardware": hw,
        "suggested_model": suggested,
        "current_default": OLLAMA_MODEL_DEFAULT,
        "models": models_info,
        "installed_models": installed,
    }


@app.post("/api/pull-model")
async def pull_model(data: dict):
    """Pull/download a model from Ollama."""
    model = data.get("model", "")
    if model not in OLLAMA_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/pull",
            json={"name": model, "stream": False},
            timeout=300,
        )
        r.raise_for_status()
        return {"success": True, "message": f"{model} downloaded successfully!"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to pull model: {str(e)}")


@app.post("/api/regression/analyze")
async def regression_analyze(
    file: UploadFile = File(...),
    recent_modification_days: Optional[int] = Form(None),
    total_execution_days: int = Form(...),
    total_testers: int = Form(...),
    cases_per_tester_per_day: int = Form(...),
    mode: str = Form("offline"),
    openai_key: Optional[str] = Form(None),
    gemini_key: Optional[str] = Form(None),
    ollama_model: Optional[str] = Form(None),
):
    contents = await file.read()
    selected_model = ollama_model or OLLAMA_MODEL_DEFAULT
    try:
        df = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Excel file: {str(e)}")

    if len(df) > 2000:
        raise HTTPException(status_code=400, detail="Max 2000 test cases allowed.")
    if len(df) == 0:
        raise HTTPException(status_code=400, detail="Excel file is empty.")
    if mode == "online" and not openai_key:
        raise HTTPException(status_code=400, detail="OpenAI API key required for Online mode.")
    if mode == "gemini" and not gemini_key:
        raise HTTPException(status_code=400, detail="Gemini API key required for Gemini mode.")

    capacity = total_execution_days * total_testers * cases_per_tester_per_day

    rows = [row.to_dict() for _, row in df.iterrows()]

    # Route to correct batch processor based on mode
    if mode == "online":
        async def _analyze_risk(row):
            return await asyncio.get_event_loop().run_in_executor(
                None, openai_analyze_risk, row, openai_key
            )
        results = await ai_manager.process_rows(rows, "openai", _analyze_risk)
    elif mode == "gemini":
        async def _analyze_risk(row):
            return await asyncio.get_event_loop().run_in_executor(
                None, gemini_analyze_risk, row, gemini_key
            )
        results = await ai_manager.process_rows(rows, "gemini", _analyze_risk)
    else:
        async def _analyze_risk(row):
            return await asyncio.get_event_loop().run_in_executor(
                None, offline_analyze_risk, row, selected_model
            )
        results = await ai_manager.process_rows(rows, "ollama", _analyze_risk)

    df["Risk Score"] = [r["risk_score"] for r in results]
    df["Priority"] = [r["priority"] for r in results]
    df["AI Risk Explanation"] = [r["explanation"] for r in results]
    df["AI Mode"] = [r.get("source", "ollama") for r in results]

    df_sorted = df.sort_values("Risk Score", ascending=False).reset_index(drop=True)
    df_sorted["Recommended for Execution"] = "No"
    if capacity > 0:
        df_sorted.loc[:capacity - 1, "Recommended for Execution"] = "Yes"

    session_id = str(uuid.uuid4())[:8]
    create_regression_excel(df_sorted, session_id, mode)

    p1 = len(df_sorted[df_sorted["Priority"] == "P1"])
    p2 = len(df_sorted[df_sorted["Priority"] == "P2"])
    p3 = len(df_sorted[df_sorted["Priority"] == "P3"])
    recommended_count = min(capacity, len(df_sorted))
    coverage_pct = round(recommended_count / len(df_sorted) * 100) if len(df_sorted) > 0 else 0

    return {
        "session_id": session_id,
        "mode": mode,
        "total_cases": len(df_sorted),
        "capacity": capacity,
        "p1_count": p1,
        "p2_count": p2,
        "p3_count": p3,
        "recommended_count": recommended_count,
        "coverage_percent": coverage_pct,
        "download_url": f"/api/download/{session_id}/regression",
        "ollama_model": selected_model
    }


@app.post("/api/automation/analyze")
async def automation_analyze(
    file: UploadFile = File(...),
    mode: str = Form("offline"),
    openai_key: Optional[str] = Form(None),
    gemini_key: Optional[str] = Form(None),
    ollama_model: Optional[str] = Form(None),
):
    contents = await file.read()
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

    if mode == "online":
        async def _analyze_auto(row):
            return await asyncio.get_event_loop().run_in_executor(
                None, openai_analyze_automation, row, openai_key
            )
        results = await ai_manager.process_rows(rows, "openai", _analyze_auto)
    elif mode == "gemini":
        async def _analyze_auto(row):
            return await asyncio.get_event_loop().run_in_executor(
                None, gemini_analyze_automation, row, gemini_key
            )
        results = await ai_manager.process_rows(rows, "gemini", _analyze_auto)
    else:
        async def _analyze_auto(row):
            return await asyncio.get_event_loop().run_in_executor(
                None, offline_analyze_automation, row, selected_model
            )
        results = await ai_manager.process_rows(rows, "ollama", _analyze_auto)

    df["Automation Suitability"] = [r["suitability"] for r in results]
    df["Confidence %"] = [r["confidence"] for r in results]
    df["AI Explanation"] = [r["explanation"] for r in results]
    df["AI Mode"] = [r.get("source", "ollama") for r in results]

    session_id = str(uuid.uuid4())[:8]
    create_automation_excel(df, session_id, mode)

    total = len(df)
    automatable = len(df[df["Automation Suitability"] == "Automatable"])
    partial = len(df[df["Automation Suitability"] == "Partial"])
    not_suitable = len(df[df["Automation Suitability"] == "Not Suitable"])

    return {
        "session_id": session_id,
        "mode": mode,
        "total_cases": total,
        "automatable_count": automatable,
        "partial_count": partial,
        "not_suitable_count": not_suitable,
        "automatable_percent": round(automatable / total * 100) if total else 0,
        "download_url": f"/api/download/{session_id}/automation",
        "ollama_model": selected_model
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