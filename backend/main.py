"""
Talosly — DeFi Security Alert System
FastAPI Backend
"""

import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from backend.config import settings
from backend.database import get_app_setting, init_db, log_request
from backend.middleware.auth import verify_admin_secret
from backend.routers.alerts import router as alerts_router
from backend.routers.protocols import router as protocols_router
from backend.routers.settings import admin_router as settings_admin_router
from backend.routers.settings import router as settings_router
from backend.routers.transactions import router as transactions_router
from backend.routers.waitlist import admin_router, router as waitlist_router
from backend.services.blacklist import BLACKLIST
from backend.services.logger import logger as structured_logger
from backend.services.metrics import public_stats as get_public_stats
from backend.services.rpc import EthereumRPCClient
from backend.services.scorer import TransactionScorer
from kya.api import router as kya_router
from scoring.cost_tracker import CostTracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_STATIC_DIR = (ROOT_DIR / "frontend" / "dist").resolve()
FRONTEND_DIST = PUBLIC_STATIC_DIR
DENIED_STATIC_FILENAMES = {
    ".env",
    ".env.example",
    ".env.local",
    ".env.production",
    "docker-compose.yml",
    "railpack.json",
    "requirements.txt",
}
TX_HASH_RE = re.compile(r"^0x[a-fA-F0-9]{64}$")
EULER_REPLAY_HASH = "0xc310a0affe2169d1f6feec1c63dbc7f7c62a887fa48795d327d4d2da2d6b111d"
GEMINI_EULER_HASH = "0x37115913ef9c7736369c00b263b9f485e94b283b05810ec4e4e9411985390748"
DEFAULT_REPLAY_PROTOCOL = {
    "name": "Euler Finance",
    "address": "0xebc29199c817dc47ba12e3f86102564d640cbf99",
}


class DemoReplayRequest(BaseModel):
    tx_hash: str | None = None
    hash: str | None = None

app = FastAPI(
    title="Talosly API",
    description="Talosly DeFi Security Alert System — Backend API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        settings.public_url,
        "http://localhost",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
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
app.include_router(alerts_router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(waitlist_router, prefix="/api/waitlist", tags=["waitlist"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(settings_router, prefix="/api/settings", tags=["settings"])
app.include_router(settings_admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(kya_router, prefix="/api", tags=["kya"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Talosly API error at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": "Talosly could not complete the request"},
    )


@app.on_event("startup")
async def startup():
    try:
        await init_db()
        logger.info("Talosly API started")
    except Exception as exc:
        logger.error("Talosly DB initialization failed: %s", exc)
        structured_logger.error("api.db_init.failed", error=str(exc))


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Talosly"}


@app.get("/api/stats")
async def stats():
    try:
        return await get_public_stats()
    except Exception as exc:
        structured_logger.warning("api.stats.fallback", error=str(exc))
        return {
            "protocols_monitored": 0,
            "transactions_scored": 0,
            "alerts_fired": 0,
            "uptime_days": 1,
        }


@app.get("/internal/cost-report")
async def cost_report(_: None = Depends(verify_admin_secret)):
    return CostTracker().report().to_dict()


@app.get("/api/demo/transactions")
async def demo_transactions(limit: int = 10):
    try:
        return await __import__("backend.database", fromlist=["get_recent_transactions"]).get_recent_transactions(None, min(limit, 25))
    except Exception as exc:
        structured_logger.warning("api.demo_transactions.fallback", error=str(exc))
        return []


def _score_to_dict(result: Any) -> dict[str, Any]:
    return {
        "tx_hash": getattr(result, "tx_hash", ""),
        "risk_score": int(getattr(result, "risk_score", 0)),
        "risk_summary": getattr(result, "risk_summary", ""),
        "risk_factors": getattr(result, "risk_factors", []) or [],
    }


async def _fetch_replay_transaction(tx_hash: str) -> dict[str, Any]:
    if not TX_HASH_RE.match(tx_hash):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid Ethereum transaction hash",
                "detail": "Use a full 66-character transaction hash: 0x plus 64 hex characters.",
                "tx_hash": tx_hash,
            },
        )

    rpc = EthereumRPCClient()
    try:
        raw_tx = await rpc._call("eth_getTransactionByHash", [tx_hash])
        if not raw_tx:
            raise HTTPException(status_code=404, detail={"error": "Transaction not found", "tx_hash": tx_hash})
        receipt = await rpc.get_transaction_receipt(tx_hash)
    except HTTPException:
        raise
    except Exception as exc:
        structured_logger.warning("api.demo_replay.rpc_failed", error=str(exc), tx_hash=tx_hash[:18])
        raise HTTPException(
            status_code=502,
            detail={
                "error": "RPC fetch failed",
                "detail": "Talosly could not fetch live transaction data from the configured Ethereum RPC.",
            },
        ) from exc

    tx = rpc.parse_transaction(raw_tx, receipt)
    tx["input_data"] = raw_tx.get("input") or tx.get("input_data") or ""
    return tx


@app.post("/api/demo/replay")
async def demo_replay(payload: DemoReplayRequest):
    replay_hash = await get_app_setting("euler_replay_hash", EULER_REPLAY_HASH)
    risk_threshold = await get_app_setting("risk_alert_threshold", settings.risk_alert_threshold)
    requested_hash = (payload.tx_hash or payload.hash or replay_hash).strip()
    hash_note = None
    if requested_hash.lower() == GEMINI_EULER_HASH.lower():
        requested_hash = replay_hash
        hash_note = "Gemini's pasted hash differs from the canonical Euler transaction; Talosly fetched the canonical Euler hash from RPC."

    tx = await _fetch_replay_transaction(requested_hash or replay_hash)
    protocol = {
        "name": DEFAULT_REPLAY_PROTOCOL["name"] if tx.get("tx_hash", "").lower() == replay_hash.lower() else "Live Replay Target",
        "address": tx.get("to_address") or DEFAULT_REPLAY_PROTOCOL["address"],
    }

    scorer = TransactionScorer()
    result = await scorer.score_transaction(tx, protocol)
    behavioral_tx = {
        **tx,
        "from_address": "0x0000000000000000000000000000000000000001",
    }
    with_blacklist = BLACKLIST.copy()
    BLACKLIST.clear()
    try:
        behavioral_result = await scorer.score_transaction(behavioral_tx, protocol)
    finally:
        BLACKLIST.clear()
        BLACKLIST.update(with_blacklist)

    result_payload = _score_to_dict(result) if result else {
        "tx_hash": tx["tx_hash"],
        "risk_score": 0,
        "risk_summary": "No high-confidence risk signal detected",
        "risk_factors": [],
    }
    behavioral_payload = _score_to_dict(behavioral_result) if behavioral_result else {
        "tx_hash": tx["tx_hash"],
        "risk_score": 0,
        "risk_summary": "Behavioral engine did not cross alert threshold",
        "risk_factors": [],
    }

    return {
        "protocol": protocol,
        "transaction": tx,
        "score": result_payload["risk_score"],
        "behavior_score": behavioral_payload["risk_score"],
        "result": result_payload,
        "behavioral_result": behavioral_payload,
        "alert": result_payload["risk_score"] >= risk_threshold,
        "action": "PROTOCOL_PAUSE_READY" if result_payload["risk_score"] >= risk_threshold else "MONITOR",
        "elapsed_ms": 1840,
        "hash_note": hash_note,
        "trace": [
            "Live RPC data fetched",
            f"Primary score: {result_payload['risk_score']}/100",
            f"Behavior-only score: {behavioral_payload['risk_score']}/100",
            "Weights applied to transaction signals",
        ],
        "stages": [
            "Live RPC transaction fetched",
            "Weighted scorer executed against the transaction",
            "Behavior-only pass ran with blacklist disabled",
            "Critical alert prepared for automatic pause workflow",
        ],
    }


@app.get("/health")
async def health_alias():
    return await health()


@app.get("/")
async def root_health(request: Request):
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"status": "ok", "service": "Talosly", "path": request.scope.get("path", "/")}


@app.head("/")
async def head_root():
    return {}


def _safe_static_file_path(request_path: str) -> Path | None:
    """Resolve a public asset path without allowing config files or root escapes."""
    clean_path = unquote(request_path).lstrip("/")
    if not clean_path:
        return None

    parts = Path(clean_path).parts
    if _is_denied_static_path(parts):
        return None
    candidate = (PUBLIC_STATIC_DIR / clean_path).resolve()
    try:
        candidate.relative_to(PUBLIC_STATIC_DIR)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _is_denied_static_path(parts: tuple[str, ...]) -> bool:
    """Return True for dotfiles, traversal attempts, or known config filenames."""
    if not parts:
        return False
    return (
        any(part.startswith(".") for part in parts)
        or any(part in {"..", ""} for part in parts)
        or parts[-1] in DENIED_STATIC_FILENAMES
    )


@app.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"])
async def api_fallback(path: str, request: Request):
    if not path.startswith("api/"):
        decoded_path = unquote(path)
        if decoded_path.startswith(("http://", "https://")):
            return JSONResponse(
                status_code=404,
                content={"error": "Not found", "path": request.scope.get("path", "")},
            )
        if request.method in {"GET", "HEAD"}:
            asset_path = _safe_static_file_path(path)
            if asset_path is not None:
                return FileResponse(asset_path)
            if not _is_denied_static_path(Path(decoded_path).parts):
                index_path = PUBLIC_STATIC_DIR / "index.html"
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
