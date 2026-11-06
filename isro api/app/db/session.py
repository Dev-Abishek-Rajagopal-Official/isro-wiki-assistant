"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


class Database:
    """Holds the engine and session factory for the application's lifetime."""

    def __init__(self, url: str | None = None) -> None:
        self.engine: AsyncEngine = create_async_engine(url or get_settings().database_url, pool_pre_ping=True,
                                                       pool_size=10, max_overflow=10)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session
