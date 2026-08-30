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
    from app.models import text_replacement  # noqa: F401 — register TextReplacement model
    from app.models import required_keyword  # noqa: F401 — register RequiredKeyword model

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add deleted_at column to routes if it doesn't exist yet
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE routes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE routes ADD COLUMN IF NOT EXISTS strip_footer BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE routes ADD COLUMN IF NOT EXISTS media_only BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE banned_words ADD COLUMN IF NOT EXISTS is_exception BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE source_channels ADD COLUMN IF NOT EXISTS invite_link VARCHAR(255)"
            )
        )

    await _seed_global_text_replacements()


# One-off global text-replacement rules seeded on every startup. Requested
# ad-signature strips that can't be found automatically (the link is a
# hidden hyperlink entity, not literal URL text, so the URL-based footer
# detector doesn't catch them) — added here rather than through the bot's
# own UI because this session has no live access to run bot commands or
# connect to the database directly. TextReplacementRepository.add() is
# idempotent (skips an existing find_text/route_id/is_exception row), so
# re-running this on every deploy is safe.
_SEEDED_GLOBAL_REPLACEMENTS: list[tuple[str, str]] = [
    ("📩 Заметил, где появился бензин? Напиши нам", ""),
    (
        "⛽️ Бак пустой, деньги в USDT? Необязательно сначала выводить их на "
        "карту — есть кошелек Алтын",
        "",
    ),
    ("📌 Актуальный список — в закреплённом посте.", ""),
]


async def _seed_global_text_replacements() -> None:
    from app.repositories.text_replacement_repo import TextReplacementRepository

    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        for find_text, replace_with in _SEEDED_GLOBAL_REPLACEMENTS:
            await repo.add(find_text, replace_with, route_id=None)
        await session.commit()


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
