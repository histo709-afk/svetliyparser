from __future__ import annotations
from typing import List
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.required_keyword import RequiredKeyword


class RequiredKeywordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, word: str, route_id: int) -> RequiredKeyword | None:
        word = word.lower().strip()
        if not word:
            return None
        existing = await self.session.execute(
            select(RequiredKeyword).where(
                RequiredKeyword.word == word, RequiredKeyword.route_id == route_id
            )
        )
        if existing.scalar_one_or_none():
            return None
        kw = RequiredKeyword(word=word, route_id=route_id)
        self.session.add(kw)
        await self.session.flush()
        return kw

    async def delete_by_id(self, kw_id: int) -> bool:
        result = await self.session.execute(delete(RequiredKeyword).where(RequiredKeyword.id == kw_id))
        return result.rowcount > 0

    async def list_for_route(self, route_id: int) -> List[RequiredKeyword]:
        result = await self.session.execute(
            select(RequiredKeyword).where(RequiredKeyword.route_id == route_id).order_by(RequiredKeyword.word)
        )
        return list(result.scalars().all())

    async def get_for_check(self, route_id: int) -> List[str]:
        result = await self.session.execute(
            select(RequiredKeyword.word).where(RequiredKeyword.route_id == route_id)
        )
        return [r for r in result.scalars().all()]
