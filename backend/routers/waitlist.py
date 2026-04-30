import hashlib
import secrets
from collections import Counter

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException

from backend import database as db
from backend.config import settings
from backend.middleware.auth import verify_admin_secret
from backend.models import WaitlistApply
from backend.services.logger import logger

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(verify_admin_secret)])


async def _send_email(to_email: str, subject: str, text: str) -> None:
    if not settings.resend_api_key:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": "Talosly <beta@talosly.com>",
                "to": [to_email],
                "subject": subject,
                "text": text,
            },
        )


@router.post("/apply", status_code=201)
async def apply_waitlist(payload: WaitlistApply):
    if await db.get_waitlist_by_email(payload.email):
        raise HTTPException(status_code=409, detail="You're already on the list. We'll be in touch.")
    try:
        waitlist_id = await db.insert_waitlist(payload.email, payload.name, payload.project, payload.twitter)
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="You're already on the list. We'll be in touch.") from None
    logger.info("waitlist.applied", email_domain=payload.email.split("@")[-1], project=payload.project)
    await _send_email(
        payload.email,
        "Talosly Beta — Application Received",
        f"Hi {payload.name or 'there'},\n\nWe received your Talosly beta application for {payload.project or 'your project'}.\n\nWe review applications within 48 hours.\n\n— The Talosly Team\n{settings.public_url}",
    )
    return {"message": "Application received. We'll review within 48 hours.", "id": waitlist_id}


@admin_router.get("/waitlist")
async def admin_waitlist():
    rows = await db.list_waitlist()
    counts = Counter(row["status"] for row in rows)
    return {
        "counts": {"pending": counts["pending"], "approved": counts["approved"], "rejected": counts["rejected"]},
        "items": rows,
    }


@admin_router.post("/waitlist/{waitlist_id}/approve")
async def approve_waitlist(waitlist_id: int):
    rows = await db.list_waitlist()
    waitlist = next((row for row in rows if row["id"] == waitlist_id), None)
    if not waitlist:
        raise HTTPException(status_code=404, detail="Waitlist application not found")
    if waitlist["status"] == "rejected":
        raise HTTPException(status_code=400, detail="Rejected applications cannot be approved")
    raw_key = "tals_" + secrets.token_hex(16)
    key_id = await db.create_api_key(
        hashlib.sha256(raw_key.encode()).hexdigest(),
        raw_key[:9],
        f"{waitlist.get('project') or waitlist.get('email')} beta key",
        waitlist_id,
    )
    await db.set_waitlist_status(waitlist_id, "approved", key_id)
    logger.info("waitlist.approved", waitlist_id=waitlist_id, key_prefix=raw_key[:9])
    await _send_email(
        waitlist["email"],
        "Talosly Beta — You're In",
        f"Hi {waitlist.get('name') or 'there'},\n\nYour Talosly beta access is approved.\n\nYour API key (save this — shown once):\n{raw_key}\n\nRate limits during beta: {settings.rate_limit_per_minute} req/min, {settings.rate_limit_per_day} req/day\n\n— The Talosly Team",
    )
    return {"api_key": raw_key, "message": "One-time display. Save this key."}


@admin_router.post("/waitlist/{waitlist_id}/reject")
async def reject_waitlist(waitlist_id: int):
    row = await db.set_waitlist_status(waitlist_id, "rejected")
    if not row:
        raise HTTPException(status_code=404, detail="Waitlist application not found")
    logger.info("waitlist.rejected", waitlist_id=waitlist_id)
    return {"message": "Application rejected"}


@admin_router.get("/metrics")
async def metrics():
    try:
        return await db.get_admin_metrics()
    except Exception as exc:
        logger.warning("admin.metrics.fallback", error=str(exc))
        return {
            "overview": {
                "total_api_keys": 0,
                "active_api_keys": 0,
                "waitlist_pending": 0,
                "protocols_monitored": 0,
                "transactions_scored_total": 0,
                "alerts_fired_total": 0,
                "requests_today": 0,
            },
            "top_keys_by_usage": [],
            "daily_requests_last_7_days": [],
            "risk_score_distribution": {
                "low_0_30": 0,
                "medium_31_60": 0,
                "elevated_61_70": 0,
                "high_71_100": 0,
            },
        }


@admin_router.get("/keys")
async def keys():
    try:
        return await db.list_api_keys()
    except Exception as exc:
        logger.warning("admin.keys.fallback", error=str(exc))
        return []


@admin_router.post("/keys/create")
async def create_manual_key(name: str = "Dev key"):
    try:
        await db.init_db()
        raw_key = "tals_" + secrets.token_hex(16)
        await db.create_api_key(hashlib.sha256(raw_key.encode()).hexdigest(), raw_key[:9], name)
        logger.info("key.created", key_prefix=raw_key[:9], name=name)
        return {"api_key": raw_key, "message": "One-time display. Save this key."}
    except Exception as exc:
        logger.error("key.create.failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"API key creation failed: {exc}") from exc


@admin_router.delete("/keys/{key_id}")
async def revoke_key(key_id: int):
    try:
        await db.init_db()
        if not await db.revoke_api_key(key_id):
            raise HTTPException(status_code=404, detail="API key not found")
        logger.info("key.revoked", key_id=key_id)
        return {"message": "API key revoked"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("key.revoke.failed", key_id=key_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"API key revoke failed: {exc}") from exc
