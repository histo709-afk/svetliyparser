from __future__ import annotations
from typing import List, Optional, Tuple
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.text_replacement import TextReplacement


class TextReplacementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, find_text: str, replace_with: str, route_id: Optional[int] = None) -> Optional[TextReplacement]:
        find_text = find_text.strip()
        if not find_text:
            return None
        existing = await self.session.execute(
            select(TextReplacement).where(
                TextReplacement.find_text == find_text,
                TextReplacement.route_id == route_id,
            )
        )
        if existing.scalar_one_or_none():
            return None
        tr = TextReplacement(find_text=find_text, replace_with=replace_with, route_id=route_id)
        self.session.add(tr)
        await self.session.flush()
        return tr

    async def delete_by_id(self, tr_id: int) -> bool:
        result = await self.session.execute(delete(TextReplacement).where(TextReplacement.id == tr_id))
        return result.rowcount > 0

    async def list_global(self) -> List[TextReplacement]:
        result = await self.session.execute(
            select(TextReplacement).where(TextReplacement.route_id.is_(None)).order_by(TextReplacement.id)
        )
        return list(result.scalars().all())

    async def list_for_route(self, route_id: int) -> List[TextReplacement]:
        result = await self.session.execute(
            select(TextReplacement).where(TextReplacement.route_id == route_id).order_by(TextReplacement.id)
        )
        return list(result.scalars().all())

    async def list_all(self) -> List[TextReplacement]:
        result = await self.session.execute(
            select(TextReplacement).order_by(TextReplacement.route_id.nulls_first(), TextReplacement.id)
        )
        return list(result.scalars().all())

    async def get_for_apply(self, route_id: int) -> List[Tuple[str, str]]:
        """Return (find_text, replace_with) pairs: global + route-specific."""
        result = await self.session.execute(
            select(TextReplacement.find_text, TextReplacement.replace_with).where(
                (TextReplacement.route_id.is_(None)) | (TextReplacement.route_id == route_id)
            )
        )
        return [(row[0], row[1]) for row in result.all()]
