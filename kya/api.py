"""FastAPI router for KYA (Know-Your-Agent) endpoints."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend import database as db
from backend.middleware.auth import verify_api_key
from kya.config import kya_settings
from kya.baselines import update_baseline
from kya.features import build_feature_vector
from kya.ingest import AgentEvent
from kya.receipts.chain import verify_receipt
from kya.score import score_agent_event

router = APIRouter(dependencies=[Depends(verify_api_key)])

_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class AgentCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    principal_ref: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    chain: str = "ethereum"
    status: str = "active"

    @field_validator("wallet_address")
    @classmethod
    def validate_wallet_address(cls, v: str) -> str:
        if not _ETH_ADDRESS_RE.match(v):
            raise ValueError("wallet_address must be a valid Ethereum address (0x followed by 40 hex characters)")
        return v.lower()


class AgentActionRequest(BaseModel):
    agent_id: int
    wallet: str
    action: str
    counterparty: str | None = None
    value: float = 0.0
    selector: str = ""
    timestamp: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    baseline: dict[str, Any] | None = None


async def _require_agent_owner(agent_id: int, api_key: dict) -> None:
    """Raise 404 if the agent doesn't exist or isn't owned by this API key."""
    pool = await db.get_pool()
    row = await pool.fetchrow(
        "SELECT owner_api_key_id FROM agents WHERE id = $1",
        agent_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Agent not found", "detail": str(agent_id)})
    if row["owner_api_key_id"] != api_key["id"]:
        raise HTTPException(status_code=403, detail={"error": "Forbidden", "detail": "This agent belongs to a different API key."})


@router.post("/v1/agents", status_code=201)
async def register_agent(payload: AgentCreateRequest, api_key: dict = Depends(verify_api_key)):
    try:
        pool = await db.get_pool()
        agent_id = await pool.fetchval(
            """
            INSERT INTO agents (name, principal_ref, status, owner_api_key_id)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            payload.name,
            payload.principal_ref,
            payload.status,
            api_key["id"],
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
        raise HTTPException(
            status_code=409,
            detail={"error": "Agent wallet already exists", "detail": payload.wallet_address},
        ) from None
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
    await _require_agent_owner(agent_id, api_key)
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
        raise HTTPException(status_code=404, detail={"error": "No scores found for agent", "detail": str(agent_id)})
    return dict(row)


@router.post("/v1/agent-score")
async def score_agent_action(payload: AgentActionRequest, api_key: dict = Depends(verify_api_key)):
    if not kya_settings.enable_kya:
        raise HTTPException(
            status_code=404,
            detail={"error": "KYA disabled", "detail": "Set ENABLE_KYA=true to enable agent scoring."},
        )

    await _require_agent_owner(payload.agent_id, api_key)

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
    if payload.baseline is not None:
        # Stateless/replay mode: use caller-supplied baseline, DB state is not updated.
        baseline = payload.baseline
    else:
        # Stateful mode (default): load from DB and update BOCPD state atomically.
        baseline = await update_baseline(payload.agent_id, event)

    score = await score_agent_event(payload.agent_id, event, baseline)
    features = build_feature_vector(event, baseline)
    return {
        "agent_id": payload.agent_id,
        "action": payload.action,
        "trust_score": score.trust_score,
        "risk_score": score.risk_score,
        "decision": score.decision,
        "risk_factors": score.risk_factors,
        "shap_top": score.shap_top,
        "confidence": score.confidence,
        "conformal": score.conformal,
        "features": features,
    }


@router.get("/v1/agents/{agent_id}/receipts")
async def get_agent_receipts(agent_id: int, limit: int = 50, api_key: dict = Depends(verify_api_key)):
    await _require_agent_owner(agent_id, api_key)
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT id, agent_id, content_hash, prev_hash, signature, payload, created_at
        FROM action_receipts
        WHERE agent_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        agent_id,
        min(max(limit, 1), 200),
    )
    return [
        {
            **{k: v for k, v in dict(row).items() if k != "payload"},
            "payload": json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"]),
        }
        for row in rows
    ]


@router.get("/v1/receipts/{receipt_id}/verify")
async def verify_receipt_endpoint(receipt_id: int, api_key: dict = Depends(verify_api_key)):
    pool = await db.get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM action_receipts WHERE id = $1",
        receipt_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Receipt not found", "detail": str(receipt_id)})

    await _require_agent_owner(row["agent_id"], api_key)

    payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else dict(row["payload"])
    valid, reason = verify_receipt(payload, row["content_hash"], row["signature"])

    if valid and row["prev_hash"] is not None:
        prev_row = await pool.fetchrow(
            "SELECT content_hash FROM action_receipts WHERE content_hash = $1",
            row["prev_hash"],
        )
        if not prev_row:
            valid = False
            reason = f"chain_broken: prev_hash={row['prev_hash'][:16]}… not found"

    return {
        "receipt_id": receipt_id,
        "agent_id": row["agent_id"],
        "valid": valid,
        "reason": reason,
        "content_hash": row["content_hash"],
        "prev_hash": row["prev_hash"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
    }
