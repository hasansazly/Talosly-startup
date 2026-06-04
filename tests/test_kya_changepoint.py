import pytest

from kya.config import kya_settings
from kya.signals.changepoint import compute_changepoint_signal


@pytest.fixture(autouse=True)
def changepoint_config(monkeypatch):
    monkeypatch.setattr(kya_settings, "kya_enable_changepoint", True)
    monkeypatch.setattr(kya_settings, "kya_cusum_drift", 0.01)
    monkeypatch.setattr(kya_settings, "kya_cusum_threshold", 0.25)


def test_changepoint_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(kya_settings, "kya_enable_changepoint", False)

    signal = compute_changepoint_signal(0.9)

    assert signal.enabled is False
    assert signal.changepoint_score == 0.0
    assert signal.cusum_state["s_high"] == 0.0


def test_stable_stream_never_fires():
    state = None

    for score in [0.1] * 20:
        signal = compute_changepoint_signal(score, state)
        state = signal.cusum_state
        assert signal.changepoint_detected is False
        assert signal.changepoint_score == 0.0

    assert state["s_high"] == 0.0
    assert state["s_low"] == 0.0


def test_sustained_upward_shift_fires_within_expected_steps():
    state = None
    for score in [0.1] * 5:
        state = compute_changepoint_signal(score, state).cusum_state

    detected_step = None
    for step in range(1, 4):
        signal = compute_changepoint_signal(0.3, state)
        state = signal.cusum_state
        if signal.changepoint_detected:
            detected_step = step
            break

    assert detected_step == 2
    assert signal.direction == "high"
    assert signal.changepoint_score == 1.0


def test_accumulator_resets_after_detection():
    state = {
        "s_high": 0.24,
        "s_low": 0.0,
        "reference_mean": 0.1,
        "count": 10,
    }

    signal = compute_changepoint_signal(0.3, state)

    assert signal.changepoint_detected is True
    assert signal.direction == "high"
    assert signal.cusum_state["s_high"] == 0.0
    assert signal.cusum_state["s_low"] == 0.0
