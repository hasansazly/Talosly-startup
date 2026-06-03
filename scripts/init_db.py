import asyncio

from backend.database import close_db, create_kya_tables, init_db


async def main() -> None:
    await init_db()
    await create_kya_tables()
    await close_db()
    print("Talosly DB initialized")


if __name__ == "__main__":
    asyncio.run(main())
