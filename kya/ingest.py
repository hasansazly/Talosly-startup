"""Manual KYA wallet ingestion built on Talosly's existing RPC client."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.services.rpc import EthereumRPCClient, EthereumRPCRateLimitError


@dataclass(frozen=True)
class AgentEvent:
    tx_hash: str
    agent_id: int
    wallet: str
    counterparty: str | None
    value: float
    selector: str
    timestamp: datetime
    raw: dict[str, Any]


async def ingest_wallet(
    agent_id: int,
    address: str,
    lookback: int,
    rpc_client: EthereumRPCClient | None = None,
) -> list[AgentEvent]:
    """Read recent activity for one agent wallet without starting a polling loop."""
    client = rpc_client or EthereumRPCClient()
    latest_block = await client.get_latest_block_number()
    from_block = max(latest_block - max(int(lookback), 0) + 1, 0)
    raw_transactions = await client.get_transactions_for_address(address, from_block, latest_block, {})
    return [_to_agent_event(client, agent_id, address, tx) for tx in raw_transactions]


def _to_agent_event(
    client: EthereumRPCClient,
    agent_id: int,
    wallet: str,
    raw_tx: dict[str, Any],
) -> AgentEvent:
    parsed = client.parse_transaction(raw_tx)
    wallet_lower = wallet.lower()
    from_address = parsed.get("from_address")
    to_address = parsed.get("to_address")
    if (from_address or "").lower() == wallet_lower:
        counterparty = to_address
    else:
        counterparty = from_address

    return AgentEvent(
        tx_hash=str(parsed.get("tx_hash") or ""),
        agent_id=agent_id,
        wallet=wallet,
        counterparty=counterparty,
        value=float(parsed.get("value_eth") or 0.0),
        selector=_selector(str(parsed.get("input_data") or "")),
        timestamp=_block_timestamp(raw_tx),
        raw=raw_tx,
    )


def _selector(input_data: str) -> str:
    clean_input = input_data.lower()
    if clean_input.startswith("0x"):
        clean_input = clean_input[2:]
    return clean_input[:8] if len(clean_input) >= 8 else ""


def _block_timestamp(raw_tx: dict[str, Any]) -> datetime:
    value = raw_tx.get("timestamp") or raw_tx.get("block_timestamp")
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(int(value, 0), tz=timezone.utc)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(timezone.utc)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


__all__ = ["AgentEvent", "EthereumRPCClient", "EthereumRPCRateLimitError", "ingest_wallet"]
