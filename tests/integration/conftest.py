import os

import asyncpg
import pytest_asyncio

import backend.database as db_module

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://talosly:talosly@localhost:5433/talosly_test",
)


@pytest_asyncio.fixture
async def real_db():
    """Spin up a real asyncpg pool against the test Postgres instance, apply
    the full schema exactly as production does, yield the pool, then drop
    everything so the next test starts clean."""
    pool = await asyncpg.create_pool(TEST_DSN, min_size=1, max_size=5)

    saved = db_module._pool
    db_module._pool = pool
    try:
        await db_module._create_tables()
    except Exception:
        db_module._pool = saved
        await pool.close()
        raise

    yield pool

    # Teardown: wipe schema so every test starts from a blank slate.
    async with pool.acquire() as conn:
        await conn.execute("DROP SCHEMA public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        await conn.execute("GRANT ALL ON SCHEMA public TO talosly")
    await pool.close()
    db_module._pool = saved
