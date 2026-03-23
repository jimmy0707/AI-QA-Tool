"""
routers/system.py
─────────────────
System-level routes:
  GET  /                          health ping
  GET  /health                    Ollama connectivity
  GET  /api/test                  backend smoke test
  GET  /api/hardware              RAM/CPU info + model suggestions
  GET  /api/rate-stats            AI rate-manager stats
  GET  /api/ai-status             AI rate-manager live status
  POST /api/validate-key          unified key validator (OpenAI + Gemini)
  POST /api/validate-openai-key   alias → validate-key
  POST /api/validate-gemini-key   alias → validate-key
  POST /api/pull-model            download an Ollama model
"""

import requests
from fastapi import APIRouter, HTTPException
from openai import OpenAI, AuthenticationError, RateLimitError
from google import genai

from config import OLLAMA_URL, OLLAMA_MODEL_DEFAULT, OLLAMA_MODELS, OUTPUT_DIR, logger
from utils.hardware import get_hardware_info, suggest_model, get_installed_models
from ai_rate_manager import ai_manager

router = APIRouter()


@router.get("/")
def root():
    return {"status": "AI QA Decision Intelligence Platform Running", "version": "1.0"}


@router.get("/health")
def health():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_status = "connected" if r.ok else "error"
    except Exception:
        ollama_status = "not reachable"
    return {"api": "healthy", "ollama": ollama_status, "model": OLLAMA_MODEL_DEFAULT}


@router.get("/api/test")
def test():
    return {"status": "backend working", "output_dir": OUTPUT_DIR}


@router.get("/api/rate-stats")
def rate_stats():
    """Live monitoring — token bucket status, cache hit rate, queue size."""
    return ai_manager.get_stats()


@router.get("/api/ai-status")
def ai_status():
    """Returns real-time rate limit usage, cache stats and queue depth."""
    return ai_manager.get_status()


@router.post("/api/validate-key")
async def validate_key(data: dict):
    """
    Auto-detect key type from format and validate against the provider.
    OpenAI keys start with: sk-
    Gemini keys start with: AIza
    """
    api_key = data.get("api_key", "").strip()

    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required.")

    if api_key.startswith("sk-"):
        key_type = "openai"
    elif api_key.startswith("AIza"):
        key_type = "gemini"
    else:
        return {
            "valid":    False,
            "key_type": "unknown",
            "message":  "Cannot identify key type. OpenAI keys start with 'sk-', Gemini keys start with 'AIza'.",
        }

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


# Aliases so existing frontend calls don't break
@router.post("/api/validate-openai-key")
async def validate_openai_key_alias(data: dict):
    return await validate_key(data)


@router.post("/api/validate-gemini-key")
async def validate_gemini_key_alias(data: dict):
    return await validate_key(data)


@router.get("/api/hardware")
def hardware_info():
    """Return hardware specs and model suggestions."""
    hw        = get_hardware_info()
    suggested = suggest_model(hw["ram_gb"])
    installed = get_installed_models()
    models_info = [
        {
            "name":         key,
            "label":        info["label"],
            "size":         info["size"],
            "ram_required": info["ram_required"],
            "speed":        info["speed"],
            "quality":      info["quality"],
            "best_for":     info["best_for"],
            "tier":         info["tier"],
            "is_suggested": key == suggested,
            "is_installed": key in installed,
        }
        for key, info in OLLAMA_MODELS.items()
    ]
    return {
        "hardware":        hw,
        "suggested_model": suggested,
        "current_default": OLLAMA_MODEL_DEFAULT,
        "models":          models_info,
        "installed_models": installed,
    }


@router.post("/api/pull-model")
async def pull_model(data: dict):
    """Pull / download a model from Ollama."""
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
