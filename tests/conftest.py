import pytest_asyncio

from backend import database
from backend.config import settings


@pytest_asyncio.fixture(autouse=True)
async def test_db():
    settings.database_path = ":memory:"
    if database._memory_db is not None:
        await database._memory_db.close()
        database._memory_db = None
    await database.init_db()
    yield
    if database._memory_db is not None:
        await database._memory_db.close()
        database._memory_db = None
