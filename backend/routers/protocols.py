import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from backend import database as db
from backend.middleware.auth import verify_api_key
from backend.models import ProtocolCreate, ProtocolResponse
from backend.services.logger import logger

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("", response_model=list[ProtocolResponse])
async def list_protocols(api_key: dict = Depends(verify_api_key)):
    protocols = await db.get_all_protocols(owner_api_key_id=api_key["id"])
    return [{**p, "is_active": bool(p["is_active"])} for p in protocols]


@router.post("", response_model=ProtocolResponse, status_code=201)
async def create_protocol(payload: ProtocolCreate, api_key: dict = Depends(verify_api_key)):
    try:
        await db.init_db()
        existing = await db.get_protocol_by_address(payload.address)
        if existing:
            raise HTTPException(status_code=409, detail={"error": "Protocol already exists", "detail": payload.address})
        protocol_id = await db.insert_protocol(payload.name, payload.address, api_key["id"])
        protocol = await db.get_protocol(protocol_id)
        return {**protocol, "is_active": bool(protocol["is_active"])}
    except HTTPException:
        raise
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail={"error": "Protocol already exists", "detail": payload.address}) from None
    except Exception as exc:
        logger.error("protocol.create.failed", error=str(exc), address=payload.address)
        raise HTTPException(status_code=500, detail=f"Protocol creation failed: {exc}") from exc


@router.delete("/{protocol_id}")
async def remove_protocol(protocol_id: int, api_key: dict = Depends(verify_api_key)):
    if not await db.delete_protocol(protocol_id, api_key["id"]):
        raise HTTPException(status_code=404, detail={"error": "Protocol not found", "detail": str(protocol_id)})
    return {"status": "ok", "service": "Talosly"}


@router.patch("/{protocol_id}/toggle", response_model=ProtocolResponse)
async def toggle_protocol(protocol_id: int, api_key: dict = Depends(verify_api_key)):
    protocol = await db.toggle_protocol(protocol_id, api_key["id"])
    if not protocol:
        raise HTTPException(status_code=404, detail={"error": "Protocol not found", "detail": str(protocol_id)})
    return {**protocol, "is_active": bool(protocol["is_active"])}
