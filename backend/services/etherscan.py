import httpx

from backend.config import settings

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAINID = "1"
TORNADO_CASH = "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b"


def _neutral_result(label: str | None = None, tx_count: int = -1) -> dict[str, bool | int | str | None]:
    return {
        "label": label,
        "is_dangerous": False,
        "is_new_wallet": False,
        "funded_by_tornado": False,
        "tx_count": tx_count,
    }


async def get_address_label(address: str) -> dict[str, bool | int | str | None]:
    """
    Derives risk signals from Etherscan V2 public API.
    Returns label info and danger flag based on behavioral signals.
    """
    if not address or not settings.etherscan_api_key:
        return _neutral_result()

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            contract_resp = await client.get(
                ETHERSCAN_V2,
                params={
                    "chainid": CHAINID,
                    "module": "contract",
                    "action": "getsourcecode",
                    "address": address,
                    "apikey": settings.etherscan_api_key,
                },
            )
            contract_data = contract_resp.json()
            contract_result = contract_data.get("result", [{}])[0]
            contract_name = contract_result.get("ContractName", "") or ""
            is_unverified_contract = (
                contract_name == ""
                and contract_result.get("ABI") == "Contract source code not verified"
            )

            tx_resp = await client.get(
                ETHERSCAN_V2,
                params={
                    "chainid": CHAINID,
                    "module": "account",
                    "action": "txlist",
                    "address": address,
                    "page": "1",
                    "offset": "10",
                    "sort": "asc",
                    "apikey": settings.etherscan_api_key,
                },
            )
            tx_data = tx_resp.json()
            txs = tx_data.get("result", [])
            txs = txs if isinstance(txs, list) else []
            tx_count = len(txs)
            is_new_wallet = tx_count <= 3
            funded_by_tornado = any(tx.get("from", "").lower() == TORNADO_CASH for tx in txs)

        is_dangerous = funded_by_tornado or (is_unverified_contract and is_new_wallet)

        label_parts = []
        if funded_by_tornado:
            label_parts.append("Tornado Cash funded")
        if is_new_wallet:
            label_parts.append(f"new wallet ({tx_count} txs)")
        if is_unverified_contract:
            label_parts.append("unverified contract")
        if contract_name:
            label_parts.append(contract_name)

        return {
            "label": ", ".join(label_parts) or "unknown",
            "is_dangerous": is_dangerous,
            "is_new_wallet": is_new_wallet,
            "funded_by_tornado": funded_by_tornado,
            "tx_count": tx_count,
        }
    except Exception:
        return _neutral_result()
