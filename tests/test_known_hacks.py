import json

from data.load_known_hacks import HackRecord, KnownHacksDB


def test_known_hacks_loads_jsonl_and_plain_hashes(tmp_path):
    path = tmp_path / "known_hacks.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "hash": "0x" + "a" * 64,
                        "protocol": "Test Protocol",
                        "amount_usd": 123,
                        "attack_type": "flash_loan",
                    }
                ),
                "0x" + "b" * 64,
                "0xnot-a-real-hash",
            ]
        )
    )

    db = KnownHacksDB(path)

    assert db.is_exploit("0x" + "A" * 64)
    assert db.is_exploit("0x" + "b" * 64)
    assert not db.is_exploit("0xnot-a-real-hash")
    assert db.get("0x" + "a" * 64).protocol == "Test Protocol"
    assert db.stats()["total_tx_hashes"] == 2


def test_known_hacks_append_rejects_duplicates(tmp_path):
    db = KnownHacksDB(tmp_path / "known_hacks.jsonl")
    record = HackRecord(hash="0x" + "c" * 64, protocol="New")

    assert db.append(record) is True
    assert db.append(record) is False
    assert db.stats()["total_tx_hashes"] == 1
