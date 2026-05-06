import httpx

from backend.config import settings

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"
CHAINID = "1"
TORNADO_CASH_ADDRESSES = {
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936",
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",
    "0xa160cdab225685da1d56aa342ad8841c3b53f291",
    "0xc2dfdfe7d39da9e51ad332e426bc7a07aa423ba0",
    "0x70b8172e628992007453aa4fe27048b59957e0ef",
    "0x4cc716e8c594330addd37cb6696e837d687e4183",
    "0xffffffff45cc70237c0eb04e4c77ac6299a42acd",
}


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
            contract_result = contract_resp.json().get("result", [{}])[0]
            contract_name = contract_result.get("ContractName", "") or ""

            txcount_resp = await client.get(
                ETHERSCAN_V2,
                params={
                    "chainid": CHAINID,
                    "module": "proxy",
                    "action": "eth_getTransactionCount",
                    "address": address,
                    "tag": "latest",
                    "apikey": settings.etherscan_api_key,
                },
            )
            txcount_hex = txcount_resp.json().get("result", "0x0") or "0x0"
            real_tx_count = int(txcount_hex, 16)
            is_new_wallet = real_tx_count <= 5

            code_resp = await client.get(
                ETHERSCAN_V2,
                params={
                    "chainid": CHAINID,
                    "module": "proxy",
                    "action": "eth_getCode",
                    "address": address,
                    "tag": "latest",
                    "apikey": settings.etherscan_api_key,
                },
            )
            code = (code_resp.json().get("result", "0x") or "0x").lower()
            is_contract = code not in {"0x", "0x0"}
            is_unverified_contract = (
                is_contract
                and contract_name == ""
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
            txs = tx_resp.json().get("result", [])
            txs = txs if isinstance(txs, list) else []
            funded_by_tornado = any(tx.get("from", "").lower() in TORNADO_CASH_ADDRESSES for tx in txs)

        is_dangerous = funded_by_tornado or (is_unverified_contract and is_new_wallet)

        label_parts = []
        if funded_by_tornado:
            label_parts.append("Tornado Cash funded")
        if is_new_wallet:
            label_parts.append(f"new wallet ({real_tx_count} txs)")
        if is_unverified_contract:
            label_parts.append("unverified contract")
        if contract_name:
            label_parts.append(contract_name)

        return {
            "label": ", ".join(label_parts) or "unknown",
            "is_dangerous": is_dangerous,
            "is_new_wallet": is_new_wallet,
            "funded_by_tornado": funded_by_tornado,
            "tx_count": real_tx_count,
        }
    except Exception as exc:
        print(f"get_address_label EXCEPTION for {address}: {type(exc).__name__}: {exc}")
        return _neutral_result()
