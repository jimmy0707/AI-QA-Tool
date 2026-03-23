"""
config.py
─────────
All environment variables, constants, and app-wide configuration.
Import from here instead of using os.getenv() scattered across files.
"""

import os
import logging

# ── Logging ──────────────────────────────────────────────────────────────────
# Windows-safe — do NOT use basicConfig as it conflicts with uvicorn on Windows
logger = logging.getLogger("ai-qa-platform")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Ollama ────────────────────────────────────────────────────────────────────
OLLAMA_URL           = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL_DEFAULT = os.getenv("OLLAMA_MODEL", "phi3")

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS: list[str] = (
    ["*"] if _raw_origins == "*"
    else [o.strip() for o in _raw_origins.split(",")]
)

# ── Ollama Model Registry ─────────────────────────────────────────────────────
OLLAMA_MODELS: dict = {
    "tinyllama": {
        "label":        "TinyLlama",
        "size":         "637 MB",
        "ram_required": 2,
        "speed":        "Instant",
        "quality":      "Good",
        "best_for":     "Very slow / old PCs (under 4 GB RAM)",
        "tier":         1,
    },
    "phi3": {
        "label":        "Phi-3 (Default)",
        "size":         "2.2 GB",
        "ram_required": 4,
        "speed":        "Fast",
        "quality":      "Very Good",
        "best_for":     "Most laptops and PCs (4-8 GB RAM)",
        "tier":         2,
    },
    "mistral": {
        "label":        "Mistral 7B",
        "size":         "4.1 GB",
        "ram_required": 8,
        "speed":        "Moderate",
        "quality":      "Excellent",
        "best_for":     "Mid-range PC (8-16 GB RAM)",
        "tier":         3,
    },
    "llama3": {
        "label":        "LLaMA 3 8B",
        "size":         "4.7 GB",
        "ram_required": 8,
        "speed":        "Moderate",
        "quality":      "Best",
        "best_for":     "Fast PC (16 GB+ RAM)",
        "tier":         4,
    },
}
