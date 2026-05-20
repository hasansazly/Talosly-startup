import json

from backend.mempool import MempoolSubscriber


async def noop_handler(_tx):
    return None


def test_extract_transaction_from_subscription_message():
    tx = {"hash": "0xabc", "to": "0xdef"}
    message = json.dumps({"params": {"result": tx}})

    assert MempoolSubscriber._extract_transaction(message) == tx


def test_extract_transaction_ignores_invalid_messages():
    assert MempoolSubscriber._extract_transaction("not json") is None
    assert MempoolSubscriber._extract_transaction(json.dumps({"params": {"result": "0xabc"}})) is None


def test_subscription_payload_filters_to_addresses():
    subscriber = MempoolSubscriber(
        "wss://example.test",
        tx_handler_callback=noop_handler,
        to_addresses=["0xdef", "0xabc", "0xdef"],
    )

    assert subscriber._subscription_payload() == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_subscribe",
        "params": [
            "alchemy_pendingTransactions",
            {"toAddress": ["0xabc", "0xdef"], "hashesOnly": False},
        ],
    }
