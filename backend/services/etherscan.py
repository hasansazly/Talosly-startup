import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

DANGER_LABELS = {"exploit", "tornado", "scammer", "phish", "hack", "heist", "sanctioned"}


async def get_address_label(address: str) -> dict[str, bool | str | None]:
    """
    Checks Etherscan to see if an address has been labeled as malicious.
    """
    if not address or not settings.etherscan_api_key:
        return {"label": None, "is_dangerous": False}

    url = (
        f"https://api.etherscan.io/api"
        f"?module=contract"
        f"&action=getsourcecode"
        f"&address={address}"
        f"&apikey={settings.etherscan_api_key}"
    )

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            data = resp.json()

            # Etherscan often puts labels in the ContractName field for exploiters.
            result = data.get("result", [{}])[0]
            label = result.get("ContractName", "") or ""

            is_dangerous = any(word in label.lower() for word in DANGER_LABELS)

            if is_dangerous:
                logger.info("ETHERSCAN DANGER DETECTED: %s is labeled '%s'", address, label)

            return {"label": label, "is_dangerous": is_dangerous}
    except Exception as exc:
        logger.error("Etherscan label lookup failed: %s", exc)
        return {"label": None, "is_dangerous": False}
