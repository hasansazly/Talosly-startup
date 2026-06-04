import pytest

from kya.signals.mahalanobis import compute_mahalanobis_signal


@pytest.fixture(autouse=True)
def enable_mahalanobis(monkeypatch):
    monkeypatch.setenv("KYA_ENABLE_MAHALANOBIS", "true")


def robust_stats(
    *,
    covariance: list[list[float]] | None = None,
    low_confidence: bool = False,
    mad: list[float] | None = None,
) -> dict:
    return {
        "feature_names": ["x", "y"],
        "median": [0.0, 0.0],
        "mad": mad or [1.0, 1.0],
        "covariance": covariance or [[1.0, 0.9], [0.9, 1.0]],
        "low_confidence": low_confidence,
    }


def test_signal_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("KYA_ENABLE_MAHALANOBIS", raising=False)

    signal = compute_mahalanobis_signal({"x": 5.0, "y": 5.0}, robust_stats())

    assert signal.enabled is False
    assert signal.method == "disabled"
    assert signal.probability == 0.0


def test_center_vector_scores_low():
    signal = compute_mahalanobis_signal({"x": 0.0, "y": 0.0}, robust_stats())

    assert signal.enabled is True
    assert signal.distance_squared == 0.0
    assert signal.probability == 0.0
    assert signal.confidence == "high"


def test_vector_far_along_correlated_axis_scores_high():
    signal = compute_mahalanobis_signal({"x": 5.0, "y": 5.0}, robust_stats())

    assert signal.distance_squared > 20.0
    assert signal.probability > 0.999
    assert signal.confidence == "high"


def test_singular_covariance_uses_regularized_pseudo_inverse():
    signal = compute_mahalanobis_signal(
        {"x": 3.0, "y": -3.0},
        robust_stats(covariance=[[1.0, 1.0], [1.0, 1.0]]),
    )

    assert signal.method == "regularized_pinv"
    assert signal.probability > 0.999
    assert signal.confidence == "high"


def test_cold_start_falls_back_to_per_feature_deviation():
    signal = compute_mahalanobis_signal(
        {"x": 4.0, "y": 0.0},
        robust_stats(low_confidence=True, mad=[1.0, 1.0]),
    )

    assert signal.method == "mad_fallback"
    assert signal.probability > 0.95
    assert signal.confidence == "low"
