from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SyncedMessage(Base):
    __tablename__ = "synced_messages"
    __table_args__ = (
        Index("ix_synced_messages_src", "source_channel_id", "source_message_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dest_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dest_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
