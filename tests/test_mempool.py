import json

from backend.mempool import MempoolSubscriber


def test_extract_transaction_from_subscription_message():
    tx = {"hash": "0xabc", "to": "0xdef"}
    message = json.dumps({"params": {"result": tx}})

    assert MempoolSubscriber._extract_transaction(message) == tx


def test_extract_transaction_ignores_invalid_messages():
    assert MempoolSubscriber._extract_transaction("not json") is None
    assert MempoolSubscriber._extract_transaction(json.dumps({"params": {"result": "0xabc"}})) is None
