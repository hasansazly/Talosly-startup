"""
Talosly — DeFi Security Alert System
FastAPI Backend
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.database import init_db
from backend.routers.alerts import router as alerts_router
from backend.routers.protocols import router as protocols_router
from backend.routers.transactions import router as transactions_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Talosly API",
    description="Talosly DeFi Security Alert System — Backend API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def normalize_vercel_paths(request: Request, call_next):
    path = request.scope.get("path", "")
    for prefix in ("/api/index.py", "/api/index"):
        if path == prefix:
            request.scope["path"] = "/api/health"
            break
        if path.startswith(f"{prefix}/"):
            request.scope["path"] = "/api/" + path.removeprefix(f"{prefix}/")
            break
    return await call_next(request)

app.include_router(protocols_router, prefix="/api/protocols", tags=["protocols"])
app.include_router(transactions_router, prefix="/api/transactions", tags=["transactions"])
app.include_router(alerts_router, prefix="/api/alerts", tags=["alerts"])

# Vercel may strip the /api prefix when a rewrite targets api/index.py.
# Keep the canonical /api routes above, and expose bare aliases for serverless routing.
app.include_router(protocols_router, prefix="/protocols", tags=["protocols"])
app.include_router(transactions_router, prefix="/transactions", tags=["transactions"])
app.include_router(alerts_router, prefix="/alerts", tags=["alerts"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Talosly API error at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": "Talosly could not complete the request"},
    )


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Talosly API started")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Talosly"}


@app.get("/health")
async def health_alias():
    return await health()
