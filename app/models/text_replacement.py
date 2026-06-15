from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def _now() -> datetime:
    return datetime.now(timezone.utc)

class TextReplacement(Base):
    __tablename__ = "text_replacements"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    find_text: Mapped[str] = mapped_column(Text, nullable=False)
    replace_with: Mapped[str] = mapped_column(Text, nullable=False, default="")
    route_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("routes.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
