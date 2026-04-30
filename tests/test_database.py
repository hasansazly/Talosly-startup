import pytest

from backend import database as db


@pytest.mark.asyncio
async def test_insert_protocol_and_get_all_protocols():
    protocol_id = await db.insert_protocol("Uniswap V3", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
    protocols = await db.get_all_protocols()
    assert protocols[0]["id"] == protocol_id
    assert protocols[0]["name"] == "Uniswap V3"


@pytest.mark.asyncio
async def test_upsert_transaction_reports_new_then_duplicate():
    protocol_id = await db.insert_protocol("Uniswap V3", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
    tx = {
        "tx_hash": "0xabc",
        "block_number": 1,
        "from_address": "0xfrom",
        "to_address": "0xto",
        "value_eth": 0.1,
        "gas_used": 21000,
        "input_data": "0x",
    }
    first_id, first_new = await db.upsert_transaction(protocol_id, tx)
    second_id, second_new = await db.upsert_transaction(protocol_id, tx)
    assert first_id == second_id
    assert first_new is True
    assert second_new is False


@pytest.mark.asyncio
async def test_insert_alert_and_mark_telegram_sent():
    protocol_id = await db.insert_protocol("Uniswap V3", "0xE592427A0AEce92De3Edee1F18E0157C05861564")
    tx_id, _ = await db.upsert_transaction(protocol_id, {"tx_hash": "0xabc"})
    alert_id = await db.insert_alert(tx_id, 90, "Talosly high risk alert")
    await db.mark_telegram_sent(alert_id)
    alerts = await db.get_alerts()
    assert alerts[0]["telegram_sent"] == 1
