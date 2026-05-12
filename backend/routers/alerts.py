from fastapi import APIRouter, Depends, HTTPException, Query

from backend import database as db
from backend.middleware.auth import verify_api_key
from backend.models import AlertFeedback, AlertFeedbackPatch, AlertResponse

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(limit: int = Query(100, ge=1, le=500)):
    alerts = await db.get_alerts(limit)
    return [{**alert, "telegram_sent": bool(alert["telegram_sent"])} for alert in alerts]


@router.get("/stats")
async def alert_stats():
    return await db.get_alert_stats()


@router.post("/{alert_id}/feedback")
async def submit_alert_feedback(alert_id: int, feedback: AlertFeedback):
    updated = await db.submit_alert_feedback(alert_id, feedback.confirmed_threat, feedback.feedback_note)
    if not updated:
        raise HTTPException(status_code=404, detail={"error": "Alert not found", "detail": alert_id})
    return {"status": "success", "message": f"Feedback recorded for alert {alert_id}"}


@router.patch("/{alert_id}/feedback")
async def patch_alert_feedback(alert_id: int, feedback: AlertFeedbackPatch):
    updated = await db.submit_alert_feedback(alert_id, feedback.feedback, None)
    if not updated:
        raise HTTPException(status_code=404, detail={"error": "Alert not found", "detail": alert_id})
    return {"status": "success", "message": f"Feedback recorded for alert {alert_id}"}
