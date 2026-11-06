"""Alembic environment (async engine). The database URL comes from the app settings."""

from __future__ import annotations

import asyncio
import sys

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.models import Base

config = context.config
target_metadata = Base.metadata

# Tables managed by other components: LangGraph checkpointer and the orchestrator's event log.
EXTERNAL_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations", "agent_events"}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in EXTERNAL_TABLES)


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    if sys.platform == "win32":  # psycopg async needs the selector loop on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_migrations_online())
