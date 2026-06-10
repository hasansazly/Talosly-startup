from kya.signals.summary import (
    CHANGEPOINT,
    CONFORMAL,
    MAHALANOBIS,
    SignalResult,
    summarize,
)
from kya.signals.guards import (
    WarmupPolicy,
    covariance_is_usable,
    is_warming_up,
)


def _r(name, enabled=True, fired=False, **kw):
    return SignalResult(name=name, enabled=enabled, fired=fired, **kw)


def test_only_enabled_and_fired_signals_count():
    out = summarize([
        _r(CHANGEPOINT, enabled=True, fired=True),
        _r(MAHALANOBIS, enabled=True, fired=False),
        _r(CONFORMAL, enabled=False, fired=True),
    ])
    assert out.signals_fired == [CHANGEPOINT]


def test_changepoint_is_always_present_first_class():
    out = summarize([_r(MAHALANOBIS, fired=True)])
    assert out.changepoint == {"enabled": False, "fired": False}
    assert MAHALANOBIS in out.detail


def test_changepoint_detail_carries_statistic_and_threshold():
    out = summarize([
        _r(CHANGEPOINT, enabled=True, fired=True, statistic=8.4, threshold=5.0, extra={"direction": "upper"}),
    ])
    cp = out.changepoint
    assert cp["fired"] is True
    assert cp["statistic"] == 8.4 and cp["threshold"] == 5.0
    assert cp["direction"] == "upper"


def test_order_is_deterministic_and_changepoint_leads():
    a = summarize([_r(CONFORMAL, fired=True), _r(CHANGEPOINT, fired=True), _r(MAHALANOBIS, fired=True)])
    b = summarize([_r(MAHALANOBIS, fired=True), _r(CONFORMAL, fired=True), _r(CHANGEPOINT, fired=True)])
    assert a.signals_fired == b.signals_fired == [CHANGEPOINT, MAHALANOBIS, CONFORMAL]


def test_warming_up_signal_does_not_fire_but_is_visible():
    out = summarize([_r(MAHALANOBIS, enabled=True, fired=False, warming_up=True)])
    assert MAHALANOBIS not in out.signals_fired
    assert out.detail[MAHALANOBIS]["warming_up"] is True


def test_summary_dict_is_stable_for_hashing():
    payload = [_r(CHANGEPOINT, fired=True, statistic=8.4, threshold=5.0)]
    assert summarize(payload).to_dict() == summarize(payload).to_dict()


def test_warming_up_below_threshold():
    assert is_warming_up(5)
    assert is_warming_up(29)
    assert not is_warming_up(30)


def test_custom_warmup_policy():
    p = WarmupPolicy(min_observations=10)
    assert is_warming_up(9, p)
    assert not is_warming_up(10, p)


def test_covariance_needs_more_samples_than_features():
    assert not covariance_is_usable(n_observations=9, n_features=8)
    assert covariance_is_usable(n_observations=30, n_features=8)
    p = WarmupPolicy(min_observations=3)
    assert not covariance_is_usable(8, 8, p)
    assert covariance_is_usable(9, 8, p)
