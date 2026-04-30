import pytest


@pytest.fixture(autouse=True)
def clear_rate_limits():
    from backend.middleware import ratelimit

    ratelimit._windows.clear()
    yield
    ratelimit._windows.clear()
