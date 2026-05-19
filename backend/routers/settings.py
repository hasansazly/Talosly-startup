from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import database as db
from backend.middleware.auth import verify_admin_secret

router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(verify_admin_secret)])


class SettingUpdate(BaseModel):
    value: Any
    value_type: str = Field(default="string", pattern="^(string|int|float|bool|json)$")
    description: str | None = None
    is_public: bool = True


@router.get("")
async def public_settings():
    return await db.get_app_settings(public_only=True)


@admin_router.get("/settings")
async def list_settings():
    return await db.get_app_settings_rows()


@admin_router.put("/settings/{key}")
async def update_setting(key: str, payload: SettingUpdate):
    try:
        return await db.set_app_setting(
            key=key,
            value=payload.value,
            value_type=payload.value_type,
            description=payload.description,
            is_public=payload.is_public,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
