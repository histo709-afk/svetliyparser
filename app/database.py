from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create all tables if they don't exist yet (for dev / migration-less startup)."""
    from app.models import channel, message, route  # noqa: F401 — register models
    from app.models import banned_word  # noqa: F401 — register BannedWord model

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add deleted_at column to routes if it doesn't exist yet
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE routes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL"
            )
        )


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
