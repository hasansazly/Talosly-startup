import asyncio

from backend.database import close_db, init_db


async def main() -> None:
    await init_db()
    await close_db()
    print("Talosly DB initialized")


if __name__ == "__main__":
    asyncio.run(main())
