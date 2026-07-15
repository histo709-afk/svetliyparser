from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def _now() -> datetime:
    return datetime.now(timezone.utc)

class BannedWord(Base):
    __tablename__ = "banned_words"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(255), nullable=False)
    route_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=True)
    # Route-specific opt-out from a global banned word: when True (route_id
    # must be set), this word is EXCLUDED from the effective list for that
    # route even though it's banned globally/elsewhere.
    is_exception: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
