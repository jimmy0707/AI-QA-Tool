"""
utils/hardware.py
─────────────────
Hardware detection helpers — RAM, CPU, installed Ollama models.
"""

import requests
import psutil
import platform

from config import OLLAMA_URL, OLLAMA_MODEL_DEFAULT, OLLAMA_MODELS


def get_hardware_info() -> dict:
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 1)
    cpu_count = psutil.cpu_count(logical=True)
    cpu_name = platform.processor() or "Unknown CPU"
    return {"ram_gb": ram_gb, "cpu_count": cpu_count, "cpu_name": cpu_name}


def suggest_model(ram_gb: int) -> str:
    """Return the best Ollama model key for the available RAM."""
    if ram_gb >= 16:
        return "llama3"
    elif ram_gb >= 8:
        return "mistral"
    elif ram_gb >= 4:
        return "phi3"
    return "tinyllama"


def get_installed_models() -> list:
    """Return list of model names currently downloaded in Ollama."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.ok:
            return [m["name"].split(":")[0] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []
