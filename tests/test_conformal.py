import math

import pytest

from kya.conformal import ConformalClassificationWrapper, evaluate_kya_risk_probability, load_kya_conformal_wrapper


def test_conformal_calibration_uses_conservative_order_statistic():
    wrapper = ConformalClassificationWrapper(target_coverage=0.8)

    threshold = wrapper.calibrate(
        calibration_probabilities=[0.95, 0.80, 0.60, 0.30, 0.20, 0.99],
        calibration_labels=[1, 1, 1, 1, 0, 0],
    )

    assert math.isclose(threshold, 0.30)
    assert wrapper.q_hat == pytest.approx(0.70)
    assert wrapper.predict_conformal_flag(0.30).high_risk is True
    assert wrapper.predict_conformal_flag(0.29).high_risk is False


def test_kya_conformal_cache_flags_high_risk_scores():
    load_kya_conformal_wrapper.cache_clear()

    low = evaluate_kya_risk_probability(0.41)
    high = evaluate_kya_risk_probability(0.42)

    assert low["high_risk"] is False
    assert high["high_risk"] is True
    assert high["target_coverage"] == pytest.approx(0.95)
    assert high["coverage_claim"] == ">=95% marginal recall for labelled threats under exchangeability"
    assert high["exchangeability_required"] is True
    assert high["positive_calibration_size"] == 200


def test_cached_threshold_meets_positive_recall_verification():
    wrapper = load_kya_conformal_wrapper()
    rows = [{"label": 1, "risk_probability": 0.42 if idx < 190 else 0.41} for idx in range(200)]

    caught = sum(1 for row in rows if row["label"] == 1 and row["risk_probability"] >= wrapper.threshold)
    positives = sum(1 for row in rows if row["label"] == 1)

    assert caught / positives >= wrapper.target_coverage
