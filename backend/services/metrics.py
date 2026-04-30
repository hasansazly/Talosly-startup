from backend import database as db


async def public_stats() -> dict:
    return await db.get_public_stats()


async def admin_metrics() -> dict:
    return await db.get_admin_metrics()
