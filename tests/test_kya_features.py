from datetime import datetime, timezone

from kya.features import baseline_deviation_features, build_feature_vector
from kya.ingest import AgentEvent
from scoring.layer3 import FEATURE_NAMES


def make_event(
    *,
    counterparty: str = "0xknown",
    value: float = 1.0,
    selector: str = "abcdef12",
    timestamp: datetime | None = None,
    raw: dict | None = None,
) -> AgentEvent:
    return AgentEvent(
        tx_hash="0xevent",
        agent_id=1,
        wallet="0xagent",
        counterparty=counterparty,
        value=value,
        selector=selector,
        timestamp=timestamp or datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        raw=raw or {"input": f"0x{selector}"},
    )


def mature_baseline() -> dict:
    return {
        "event_count": 20,
        "known_counterparties": ["0xknown"],
        "selectors_seen": ["abcdef12"],
        "active_hours": {"12": 10},
        "value_stats": {"count": 20, "mean": 1.0, "std": 0.1},
        "cadence_stats": {
            "count": 10,
            "mean_seconds": 600.0,
            "std_seconds": 30.0,
            "last_timestamp": datetime(2026, 1, 1, 12, tzinfo=timezone.utc).isoformat(),
        },
    }


def test_build_feature_vector_contains_layer3_shape_and_kya_deviation_keys():
    features = build_feature_vector(make_event(), mature_baseline())

    for name in FEATURE_NAMES:
        assert name in features
    assert {
        "kya_new_counterparty",
        "kya_value_z_score",
        "kya_cadence_break",
        "kya_cadence_z_score",
        "kya_off_hours",
        "kya_unseen_selector",
    } <= set(features)
    assert isinstance(features["tornado_tagged"], bool)


def test_cold_baseline_does_not_create_false_deviation():
    features = build_feature_vector(
        make_event(counterparty="0xnew", value=50.0, selector="deadbeef"),
        {},
    )

    assert features["kya_new_counterparty"] is True
    assert features["kya_unseen_selector"] is True
    assert features["kya_value_z_score"] == 0.0
    assert features["kya_cadence_break"] is False
    assert features["kya_off_hours"] is False


def test_deviating_event_sets_baseline_deviation_features_and_maps_to_layer3():
    event = make_event(
        counterparty="0xnew",
        value=5.0,
        selector="deadbeef",
        timestamp=datetime(2026, 1, 1, 14, tzinfo=timezone.utc),
        raw={
            "input": "0xdeadbeef" + "00" * 16,
            "gas_price_gwei": 500.0,
            "sender_first_seen_ts": (datetime(2025, 12, 30, 14, tzinfo=timezone.utc)).timestamp(),
            "tornado_tagged": True,
        },
    )

    deviation = baseline_deviation_features(event, mature_baseline())
    features = build_feature_vector(event, mature_baseline())

    assert deviation == {
        "new_counterparty": True,
        "value_z_score": 40.0,
        "cadence_break": True,
        "cadence_z_score": 220.0,
        "off_hours": True,
        "unseen_selector": True,
    }
    assert features["kya_new_counterparty"] is True
    assert features["kya_cadence_break"] is True
    assert features["kya_off_hours"] is True
    assert features["kya_unseen_selector"] is True
    assert features["graph_centrality"] == 1.0
    assert features["pool_drain_ratio"] == 1.0
    assert features["flash_loan_fingerprint"] >= 0.6
    assert features["velocity"] == 20.0
    assert features["gas_anomaly_zscore"] == 50.0
    assert features["wallet_age_days"] == 2.0
    assert features["tornado_tagged"] is True
