from fastapi import APIRouter, HTTPException, Query

from backend import database as db
from backend.models import RiskScoreResponse, TransactionResponse
from backend.services.scorer import TransactionScorer

router = APIRouter()


@router.get("", response_model=list[TransactionResponse])
async def list_transactions(protocol_id: int | None = None, limit: int = Query(50, ge=1, le=200)):
    return await db.get_recent_transactions(protocol_id, limit)


@router.get("/{tx_hash}", response_model=TransactionResponse)
async def get_transaction(tx_hash: str):
    tx = await db.get_transaction_by_hash(tx_hash)
    if not tx:
        raise HTTPException(status_code=404, detail={"error": "Transaction not found", "detail": tx_hash})
    return tx


@router.post("/{tx_hash}/score", response_model=RiskScoreResponse)
async def score_transaction(tx_hash: str):
    tx = await db.get_transaction_by_hash(tx_hash)
    if not tx:
        raise HTTPException(status_code=404, detail={"error": "Transaction not found", "detail": tx_hash})
    protocol = await db.get_protocol(tx["protocol_id"])
    scorer = TransactionScorer()
    score = await scorer.score_transaction(tx, protocol or {})
    await db.update_transaction_score(tx["id"], score.risk_score, score.risk_summary)
    return score
