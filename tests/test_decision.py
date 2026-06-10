from kya.decision import (
    ALLOW,
    BLOCK,
    REVIEW,
    DecisionPolicy,
    decide,
)


def test_high_trust_no_signals_allows():
    d = decide(95, [])
    assert d.decision == ALLOW
    assert d.reasons


def test_mid_trust_reviews():
    assert decide(55, []).decision == REVIEW


def test_low_trust_blocks():
    assert decide(11, []).decision == BLOCK


def test_review_boundary_is_strict():
    assert decide(70, []).decision == ALLOW
    assert decide(69, []).decision == REVIEW


def test_block_boundary_is_strict():
    assert decide(40, []).decision == REVIEW
    assert decide(39, []).decision == BLOCK


def test_changepoint_forces_review_even_when_trust_is_high():
    d = decide(95, ["changepoint"])
    assert d.decision == REVIEW
    assert any("changepoint" in r for r in d.reasons)


def test_changepoint_plus_low_trust_blocks_and_records_both_reasons():
    d = decide(11, ["mahalanobis", "changepoint"])
    assert d.decision == BLOCK
    joined = " ".join(d.reasons)
    assert "block_below" in joined and "changepoint" in joined


def test_non_escalating_signal_does_not_raise_floor():
    assert decide(95, ["mahalanobis"]).decision == ALLOW


def test_custom_policy_thresholds_respected():
    strict = DecisionPolicy(block_below=60, review_below=90)
    assert decide(75, [], strict).decision == REVIEW
    assert decide(55, [], strict).decision == BLOCK


def test_decision_is_deterministic_for_receipt_hashing():
    a = decide(11, ["changepoint", "mahalanobis"]).to_dict()
    b = decide(11, ["mahalanobis", "changepoint"]).to_dict()
    assert a == b


def test_thresholds_are_recorded_for_the_receipt():
    d = decide(50, [])
    assert d.thresholds["block_below"] == 40
    assert d.thresholds["review_below"] == 70
    assert d.policy_version == "1.0.0"
