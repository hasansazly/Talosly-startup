import asyncio
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import async_engine_from_config

from backend.config import settings


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_dotenv()
target_metadata = None


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def database_urls() -> list[str]:
    urls = [settings.database_url]
    if settings.database_public_url and settings.database_public_url not in urls:
        urls.append(settings.database_public_url)
    return [normalize_database_url(url) for url in urls]


def run_migrations_offline() -> None:
    context.configure(url=database_urls()[0], target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    last_error: Exception | None = None

    for url in database_urls():
        configuration = config.get_section(config.config_ini_section, {})
        configuration["sqlalchemy.url"] = url
        connectable = async_engine_from_config(configuration, prefix="sqlalchemy.")

        try:
            async with connectable.connect() as connection:
                await connection.run_sync(do_run_migrations)
            return
        except Exception as exc:
            last_error = exc
        finally:
            await connectable.dispose()

    assert last_error is not None
    raise last_error


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
