"""
Talosly — DeFi Security Alert System
FastAPI Backend
"""

import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.config import settings
from backend.database import init_db, log_request
from backend.routers.alerts import router as alerts_router
from backend.routers.protocols import router as protocols_router
from backend.routers.transactions import router as transactions_router
from backend.routers.waitlist import admin_router, router as waitlist_router
from backend.services.logger import logger as structured_logger
from backend.services.metrics import public_stats as get_public_stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"

app = FastAPI(
    title="Talosly API",
    description="Talosly DeFi Security Alert System — Backend API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, settings.public_url, "http://localhost", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def normalize_vercel_paths(request: Request, call_next):
    started = time.perf_counter()
    path = request.scope.get("path", "")
    for prefix in ("/api/index.py", "/api/index"):
        if path == prefix:
            request.scope["path"] = "/api/health"
            break
        if path.startswith(f"{prefix}/"):
            request.scope["path"] = "/api/" + path.removeprefix(f"{prefix}/")
            break
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    api_key = getattr(request.state, "api_key", None)
    if path.startswith("/api"):
        try:
            await log_request(api_key.get("id") if api_key else None, path, request.method, response.status_code, duration_ms)
        except Exception:
            structured_logger.warning("api.request_log.failed", endpoint=path)
        structured_logger.info("api.request", endpoint=path, method=request.method, status=response.status_code, duration_ms=duration_ms)
    return response

app.include_router(protocols_router, prefix="/api/protocols", tags=["protocols"])
app.include_router(transactions_router, prefix="/api/transactions", tags=["transactions"])
app.include_router(alerts_router, prefix="/api/alerts", tags=["alerts"])
app.include_router(waitlist_router, prefix="/api/waitlist", tags=["waitlist"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])


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


@app.get("/api/stats")
async def stats():
    return await get_public_stats()


@app.get("/api/demo/transactions")
async def demo_transactions(limit: int = 10):
    return await __import__("backend.database", fromlist=["get_recent_transactions"]).get_recent_transactions(None, min(limit, 25))


@app.get("/health")
async def health_alias():
    return await health()


@app.get("/")
async def root_health(request: Request):
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"status": "ok", "service": "Talosly", "path": request.scope.get("path", "/")}


@app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
async def api_fallback(path: str, request: Request):
    if not path.startswith("api/"):
        asset_path = (FRONTEND_DIST / path).resolve()
        if FRONTEND_DIST in asset_path.parents and asset_path.is_file():
            return FileResponse(asset_path)
        index_path = FRONTEND_DIST / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not found",
            "service": "Talosly",
            "path": request.scope.get("path", ""),
            "raw_path": request.scope.get("raw_path", b"").decode("utf-8", errors="ignore"),
        },
    )
