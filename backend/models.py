import re
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class ProtocolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        if not ETH_ADDRESS_RE.match(value):
            raise ValueError("Must be a valid Ethereum address")
        return value


class ProtocolResponse(BaseModel):
    id: int
    name: str
    address: str
    chain: str
    is_active: bool
    created_at: str
    last_seen_block: Optional[int] = None


class TransactionResponse(BaseModel):
    id: int
    tx_hash: str
    from_address: Optional[str]
    to_address: Optional[str]
    value_eth: Optional[float]
    risk_score: Optional[int]
    risk_summary: Optional[str]
    fetched_at: str


class AlertResponse(BaseModel):
    id: int
    transaction_id: int
    tx_hash: str
    protocol_name: str
    risk_score: int
    risk_summary: Optional[str]
    telegram_sent: bool
    created_at: str


class RiskScoreResponse(BaseModel):
    tx_hash: str
    risk_score: int = Field(ge=0, le=100)
    risk_summary: str
    risk_factors: List[str] = Field(default_factory=list, max_length=3)


class WaitlistApply(BaseModel):
    email: EmailStr
    name: Optional[str] = Field(default=None, max_length=120)
    project: Optional[str] = Field(default=None, max_length=160)
    twitter: Optional[str] = Field(default=None, max_length=80)
    goal: Optional[str] = Field(default=None, max_length=1000)


class WaitlistResponse(BaseModel):
    id: int
    email: str
    name: Optional[str]
    project: Optional[str]
    twitter: Optional[str]
    status: str
    api_key_id: Optional[int]
    applied_at: str
    reviewed_at: Optional[str]
