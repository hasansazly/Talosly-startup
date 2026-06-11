import pytest


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False)


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="needs --integration flag")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def clear_rate_limits():
    from backend.middleware import ratelimit

    ratelimit._windows.clear()
    yield
    ratelimit._windows.clear()
