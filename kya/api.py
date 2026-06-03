"""FastAPI router for additive KYA endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import database as db
from backend.middleware.auth import verify_api_key
from kya.config import kya_settings
from kya.features import build_feature_vector
from kya.ingest import AgentEvent
from kya.score import score_agent_event

router = APIRouter(dependencies=[Depends(verify_api_key)])


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    principal_ref: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    chain: str = "ethereum"
    status: str = "active"


class AgentActionRequest(BaseModel):
    agent_id: int
    wallet: str
    action: str
    counterparty: str | None = None
    value: float = 0.0
    selector: str = ""
    timestamp: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    baseline: dict[str, Any] = Field(default_factory=dict)


@router.post("/v1/agents", status_code=201)
async def register_agent(payload: AgentCreateRequest, api_key: dict = Depends(verify_api_key)):
    try:
        pool = await db.get_pool()
        agent_id = await pool.fetchval(
            """
            INSERT INTO agents (name, principal_ref, status)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            payload.name,
            payload.principal_ref,
            payload.status,
        )
        wallet_id = await pool.fetchval(
            """
            INSERT INTO agent_wallets (agent_id, chain, address)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            agent_id,
            payload.chain,
            payload.wallet_address,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail={"error": "Agent wallet already exists", "detail": payload.wallet_address}) from None
    return {
        "id": agent_id,
        "name": payload.name,
        "principal_ref": payload.principal_ref,
        "status": payload.status,
        "wallet": {
            "id": wallet_id,
            "agent_id": agent_id,
            "chain": payload.chain,
            "address": payload.wallet_address,
        },
        "owner_api_key_id": api_key["id"],
    }


@router.get("/v1/agents/{agent_id}/score")
async def get_agent_score(agent_id: int, api_key: dict = Depends(verify_api_key)):
    pool = await db.get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, agent_id, trust_score, risk_factors, shap_top, confidence, computed_at
        FROM agent_scores
        WHERE agent_id = $1
        ORDER BY computed_at DESC
        LIMIT 1
        """,
        agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Agent score not found", "detail": str(agent_id)})
    return dict(row)


@router.post("/v1/agent-score")
async def score_agent_action(payload: AgentActionRequest, api_key: dict = Depends(verify_api_key)):
    if not kya_settings.enable_kya:
        raise HTTPException(status_code=404, detail={"error": "KYA disabled", "detail": "Set ENABLE_KYA=true to enable agent scoring."})

    event = AgentEvent(
        tx_hash=payload.action,
        agent_id=payload.agent_id,
        wallet=payload.wallet,
        counterparty=payload.counterparty,
        value=payload.value,
        selector=payload.selector,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
        raw=payload.raw,
    )
    score = await score_agent_event(payload.agent_id, event, payload.baseline)
    features = build_feature_vector(event, payload.baseline)
    return {
        "agent_id": payload.agent_id,
        "action": payload.action,
        "trust_score": score.trust_score,
        "risk_factors": score.risk_factors,
        "shap_top": score.shap_top,
        "confidence": score.confidence,
        "features": features,
    }
