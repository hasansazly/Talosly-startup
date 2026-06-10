"""FastAPI router for additive KYA endpoints."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import database as db
from backend.middleware.auth import verify_api_key
from backend.services.telegram import TelegramService
from kya.config import kya_settings
from kya.decision import decide
from kya.features import build_feature_vector
from kya.ingest import AgentEvent
from kya.receipts.receipt import verify_receipt
from kya.receipts.store import get_receipt_for_owner, list_receipts_for_agent
from kya.score import get_decision_policy, score_agent_event

router = APIRouter(dependencies=[Depends(verify_api_key)])
EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


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


@router.get("/v1/agents")
async def list_agents(api_key: dict = Depends(verify_api_key)):
    return await db.get_agents_for_owner(api_key["id"])


@router.post("/v1/agents", status_code=201)
async def register_agent(payload: AgentCreateRequest, api_key: dict = Depends(verify_api_key)):
    chain = payload.chain.strip().lower()
    wallet_address = payload.wallet_address.strip()
    supported_chains = {
        item.strip().lower()
        for item in kya_settings.kya_supported_chains.split(",")
        if item.strip()
    }
    if chain not in supported_chains:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Unsupported chain",
                "detail": f"Supported chains: {', '.join(sorted(supported_chains))}",
            },
        )
    if chain in {"ethereum", "base"} and not EVM_ADDRESS_RE.fullmatch(wallet_address):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid wallet address",
                "detail": f"{chain} wallet addresses must be 0x followed by 40 hexadecimal characters",
            },
        )
    try:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                agent_id = await conn.fetchval(
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
                wallet_id = await conn.fetchval(
                    """
                    INSERT INTO agent_wallets (agent_id, chain, address)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    agent_id,
                    chain,
                    wallet_address,
                )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail={"error": "Agent wallet already exists", "detail": wallet_address}) from None
    return {
        "id": agent_id,
        "name": payload.name,
        "principal_ref": payload.principal_ref,
        "status": payload.status,
        "wallet": {
            "id": wallet_id,
            "agent_id": agent_id,
            "chain": chain,
            "address": wallet_address,
        },
        "owner_api_key_id": api_key["id"],
    }


@router.get("/v1/agents/{agent_id}/score")
async def get_agent_score(agent_id: int, api_key: dict = Depends(verify_api_key)):
    row = await db.get_agent_score_for_owner(agent_id, api_key["id"])
    if not row:
        raise HTTPException(status_code=404, detail={"error": "Agent score not found", "detail": str(agent_id)})
    return row


@router.get("/v1/agents/{agent_id}/receipts")
async def get_agent_receipts(agent_id: int, limit: int = 100, api_key: dict = Depends(verify_api_key)):
    agent = await db.get_agent_for_owner(agent_id, api_key["id"])
    if not agent:
        raise HTTPException(status_code=404, detail={"error": "Agent not found", "detail": str(agent_id)})
    pool = await db.get_pool()
    return await list_receipts_for_agent(pool, agent_id, limit)


@router.get("/v1/receipts/{receipt_id}/verify")
async def verify_action_receipt(receipt_id: str, api_key: dict = Depends(verify_api_key)):
    pool = await db.get_pool()
    receipt = await get_receipt_for_owner(pool, receipt_id, api_key["id"])
    if not receipt:
        raise HTTPException(status_code=404, detail={"error": "Receipt not found", "detail": receipt_id})
    return {"receipt": receipt, "verification": verify_receipt(receipt)}


@router.post("/v1/agents/{agent_id}/test-alert")
async def send_agent_test_alert(agent_id: int, api_key: dict = Depends(verify_api_key)):
    agent = await db.get_agent_for_owner(agent_id, api_key["id"])
    if not agent:
        raise HTTPException(status_code=404, detail={"error": "Agent not found", "detail": str(agent_id)})

    delivered = await TelegramService().send_message(
        f"Talosly KYA test alert for {agent['name']}. Monitoring delivery is configured."
    )
    if not delivered:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Test alert delivery failed",
                "detail": "Check the configured Telegram bot token and chat ID",
            },
        )
    return {"status": "success", "message": "Test alert sent. Monitoring delivery confirmed."}


@router.post("/v1/agent-score")
async def score_agent_action(payload: AgentActionRequest, api_key: dict = Depends(verify_api_key)):
    if not await db.get_agent_for_owner(payload.agent_id, api_key["id"]):
        raise HTTPException(status_code=404, detail={"error": "Agent not found", "detail": str(payload.agent_id)})
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
    decision = decide(score.trust_score, score.signals_fired, get_decision_policy())
    features = build_feature_vector(event, payload.baseline)
    return {
        "agent_id": payload.agent_id,
        "action": payload.action,
        "trust_score": score.trust_score,
        "risk_factors": score.risk_factors,
        "shap_top": score.shap_top,
        "confidence": score.confidence,
        "features": features,
        "decision": decision.decision,
        "decision_detail": decision.to_dict(),
        "signals_detail": score.signals_detail,
        "changepoint": score.changepoint,
    }
