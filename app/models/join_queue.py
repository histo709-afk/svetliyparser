from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JoinQueueItem(Base):
    """A source channel waiting for the userbot to join it.

    Joining is the one step of adding a source that Telegram rate-limits hard
    (a few dozen joins, then flood waits of up to hours), so a large base can't
    be joined inside a single handler call. The queue is worked off in the
    background and lives in the database, so a deploy mid-way through doesn't
    lose the remainder.
    """

    __tablename__ = "join_queue"
    __table_args__ = (
        UniqueConstraint("link", "dest_telegram_id", name="uq_join_queue_link_dest"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    link: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dest_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Lower goes first. Import order by default, so a list sorted by value
    # gets its most valuable channels connected first.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pending / done / failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    batch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )
