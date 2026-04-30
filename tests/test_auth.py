import pytest
from fastapi import HTTPException

from backend.middleware.ratelimit import check_rate_limit


def test_rate_limit_allows_configured_requests(monkeypatch):
    monkeypatch.setattr("backend.middleware.ratelimit.settings.rate_limit_per_minute", 2)
    monkeypatch.setattr("backend.middleware.ratelimit.settings.rate_limit_per_day", 10)
    first = check_rate_limit(1)
    second = check_rate_limit(1)
    assert first["X-RateLimit-Remaining"] == "1"
    assert second["X-RateLimit-Remaining"] == "0"


def test_rate_limit_raises_429(monkeypatch):
    monkeypatch.setattr("backend.middleware.ratelimit.settings.rate_limit_per_minute", 1)
    monkeypatch.setattr("backend.middleware.ratelimit.settings.rate_limit_per_day", 10)
    check_rate_limit(1)
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(1)
    assert exc.value.status_code == 429
