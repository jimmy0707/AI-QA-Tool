"""
main.py
───────
Entry point — creates the FastAPI app and registers all routers.
No business logic lives here. All logic is in routers/ and services/.

Run with:
    uvicorn main:app --reload --port 8000
"""

import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOWED_ORIGINS, logger
from ai_rate_manager import ai_manager
from database import init_db

from routers.system     import router as system_router
from routers.regression import router as regression_router
from routers.automation import router as automation_router
from routers.dashboard   import router as dashboard_router

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

# ── Request Logging Middleware ────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()

    # Log incoming request
    logger.info(f"=>  {request.method} {request.url.path}")

    # Process request
    response = await call_next(request)

    # Log response with status + duration
    duration = round((time.time() - start) * 1000)
    status   = response.status_code
    icon     = "OK" if status < 400 else "ERR"
    logger.info(f"[{icon}] {request.method} {request.url.path} -> {status} ({duration}ms)")

    return response

# ── Startup ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    app.openapi_schema = None
    init_db()
    logger.info("Database tables ready")
    await ai_manager.initialize()
    logger.info("AI Rate Manager ready")
    logger.info("Server started  -> http://localhost:8000")
    logger.info("Swagger UI      -> http://localhost:8000/docs")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(system_router)
app.include_router(regression_router)
app.include_router(automation_router)
app.include_router(dashboard_router)