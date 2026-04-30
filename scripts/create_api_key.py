import argparse
import asyncio
import hashlib
import secrets

from backend import database as db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Talosly beta API key")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", default="")
    args = parser.parse_args()

    await db.init_db()
    raw_key = "tals_" + secrets.token_hex(16)
    await db.create_api_key(hashlib.sha256(raw_key.encode()).hexdigest(), raw_key[:9], args.name)
    await db.close_db()
    print("Talosly API key created. Save it now; it will not be shown again.")
    print(raw_key)


if __name__ == "__main__":
    asyncio.run(main())
