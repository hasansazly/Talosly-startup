import asyncio
import hashlib

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend import database as db
from backend.config import settings
from backend.middleware.ratelimit import check_rate_limit

security = HTTPBearer(auto_error=True)


async def verify_api_key(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    key = credentials.credentials
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    row = await db.find_api_key_by_hash(key_hash)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    headers = check_rate_limit(row["id"])
    row["rate_limit_headers"] = headers
    request.state.api_key = row
    asyncio.create_task(db.update_key_usage(row["id"]))
    return row


async def verify_admin_secret(x_admin_secret: str | None = Header(default=None)) -> None:
    if not x_admin_secret or x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
