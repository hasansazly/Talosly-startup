from fastapi import APIRouter, Query

from backend import database as db
from backend.models import AlertResponse

router = APIRouter()


@router.get("", response_model=list[AlertResponse])
async def list_alerts(limit: int = Query(100, ge=1, le=500)):
    alerts = await db.get_alerts(limit)
    return [{**alert, "telegram_sent": bool(alert["telegram_sent"])} for alert in alerts]


@router.get("/stats")
async def alert_stats():
    return await db.get_alert_stats()
