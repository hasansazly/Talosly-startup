import json
import subprocess
import sys

from data.load_known_bad_agents import BadAgentRecord, KnownBadAgentsDB


def test_known_bad_agents_loads_jsonl_and_plain_identifiers(tmp_path):
    path = tmp_path / "known_bad_agents.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "agent_id": "agent-1",
                        "principal_ref": "agent://bad",
                        "wallet": "0xBAD",
                        "reason": "drained_funds",
                    }
                ),
                "agent-2",
                "{}",
            ]
        )
    )

    db = KnownBadAgentsDB(path)

    assert db.is_bad("agent-1")
    assert db.is_bad("agent://bad")
    assert db.is_bad("0xbad")
    assert db.is_bad("agent-2")
    assert not db.is_bad("agent-3")


def test_known_bad_agents_append_rejects_duplicates(tmp_path):
    db = KnownBadAgentsDB(tmp_path / "known_bad_agents.jsonl")
    record = BadAgentRecord(agent_id="agent-1", principal_ref="agent://bad")

    assert db.append(record) is True
    assert db.append(record) is False
    assert db.stats()["unique_agents"] == 1


def test_train_kya_synthetic_smoke(tmp_path):
    model_dir = tmp_path / "kya-model"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/train_kya.py",
            "--synthetic",
            "--model-dir",
            str(model_dir),
            "--seed",
            "7",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "KYA VALIDATION METRICS" in result.stdout
    assert (model_dir / "isolation_forest.pkl").exists()
    assert (model_dir / "gbm.pkl").exists()
