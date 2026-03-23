"""
main.py
───────
Entry point — creates the FastAPI app and registers all routers.
No business logic lives here. All logic is in routers/ and services/.

Run with:
    uvicorn main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOWED_ORIGINS, logger
from ai_rate_manager import ai_manager

from routers.system     import router as system_router
from routers.regression import router as regression_router
from routers.automation import router as automation_router

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AI QA Decision Intelligence Platform",
    version="2.0",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await ai_manager.initialize()
    logger.info("AI Rate Manager ready")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(system_router)
app.include_router(regression_router)
app.include_router(automation_router)
