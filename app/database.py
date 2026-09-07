from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

log = structlog.get_logger(__name__)

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


# Columns added after the initial schema, as (table, column, DDL).
#
# Deliberately NOT written as `ADD COLUMN IF NOT EXISTS`: Postgres takes an
# AccessExclusiveLock for that statement even when the column already exists
# and the statement does nothing. During a rolling deploy the outgoing
# container is still running SELECTs holding AccessShareLock on the same
# tables, and the two deadlock — which is exactly how a boot died on
# 6 September, taking the whole service down. Checking the catalog first means
# that after the first successful run these take no locks at all.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("routes", "deleted_at",
     "ALTER TABLE routes ADD COLUMN deleted_at TIMESTAMPTZ DEFAULT NULL"),
    ("routes", "strip_footer",
     "ALTER TABLE routes ADD COLUMN strip_footer BOOLEAN NOT NULL DEFAULT FALSE"),
    ("routes", "media_only",
     "ALTER TABLE routes ADD COLUMN media_only BOOLEAN NOT NULL DEFAULT FALSE"),
    ("banned_words", "is_exception",
     "ALTER TABLE banned_words ADD COLUMN is_exception BOOLEAN NOT NULL DEFAULT FALSE"),
    ("source_channels", "invite_link",
     "ALTER TABLE source_channels ADD COLUMN invite_link VARCHAR(255)"),
]

_COLUMN_EXISTS_SQL = text(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_name = :table AND column_name = :column"
)


async def _run_column_migrations() -> None:
    """Apply pending column additions, one transaction each.

    A migration that cannot get its lock right now is logged and skipped
    rather than raised: the next boot retries it, whereas letting it escape
    kills the process before the management bot ever starts.
    """
    for table, column, ddl in _COLUMN_MIGRATIONS:
        try:
            async with engine.begin() as conn:
                already = await conn.execute(
                    _COLUMN_EXISTS_SQL, {"table": table, "column": column}
                )
                if already.first() is not None:
                    continue
                # Fail fast instead of queueing behind a long-running reader.
                await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                await conn.execute(text(ddl))
                log.info("column_migration_applied", table=table, column=column)
        except Exception as exc:
            log.warning(
                "column_migration_deferred",
                table=table,
                column=column,
                error=str(exc)[:160],
            )


async def init_db() -> None:
    """Create all tables if they don't exist yet (for dev / migration-less startup)."""
    from app.models import channel, message, route  # noqa: F401 — register models
    from app.models import banned_word  # noqa: F401 — register BannedWord model
    from app.models import text_replacement  # noqa: F401 — register TextReplacement model
    from app.models import required_keyword  # noqa: F401 — register RequiredKeyword model

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _run_column_migrations()
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
    (
        "Заправляетесь каждую неделю? Получайте бонусы за то, на что всё "
        "равно тратите деньги, с Drive",
        "",
    ),
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
