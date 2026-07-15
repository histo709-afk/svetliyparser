from __future__ import annotations
from typing import List, Optional
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.banned_word import BannedWord

class BannedWordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, word: str, route_id: Optional[int] = None, is_exception: bool = False) -> BannedWord:
        # Normalize: lowercase, strip
        word = word.lower().strip()
        # Check duplicate
        existing = await self.session.execute(
            select(BannedWord).where(
                BannedWord.word == word,
                BannedWord.route_id == route_id,
                BannedWord.is_exception == is_exception,
            )
        )
        if existing.scalar_one_or_none():
            return None  # already exists
        bw = BannedWord(word=word, route_id=route_id, is_exception=is_exception)
        self.session.add(bw)
        await self.session.flush()
        return bw

    async def delete_by_id(self, word_id: int) -> bool:
        result = await self.session.execute(delete(BannedWord).where(BannedWord.id == word_id))
        return result.rowcount > 0

    async def list_global(self) -> List[BannedWord]:
        result = await self.session.execute(
            select(BannedWord).where(BannedWord.route_id.is_(None)).order_by(BannedWord.word)
        )
        return list(result.scalars().all())

    async def list_for_route(self, route_id: int) -> List[BannedWord]:
        result = await self.session.execute(
            select(BannedWord).where(BannedWord.route_id == route_id).order_by(BannedWord.word)
        )
        return list(result.scalars().all())

    async def list_all(self) -> List[BannedWord]:
        result = await self.session.execute(select(BannedWord).order_by(BannedWord.route_id.nulls_first(), BannedWord.word))
        return list(result.scalars().all())

    async def get_for_check(self, route_id: int) -> List[str]:
        """Effective banned words for this route: global + route-specific
        bans, MINUS any route-specific exceptions (opt-outs from a global ban)."""
        result = await self.session.execute(
            select(BannedWord.word).where(
                ((BannedWord.route_id.is_(None)) | (BannedWord.route_id == route_id)),
                BannedWord.is_exception.is_(False),
            )
        )
        words = {r for r in result.scalars().all()}

        exceptions = await self.session.execute(
            select(BannedWord.word).where(
                BannedWord.route_id == route_id,
                BannedWord.is_exception.is_(True),
            )
        )
        words -= {r for r in exceptions.scalars().all()}
        return list(words)

    async def search(self, query: str) -> List[BannedWord]:
        q = query.lower().strip()
        result = await self.session.execute(
            select(BannedWord).where(BannedWord.word.contains(q)).order_by(BannedWord.word)
        )
        return list(result.scalars().all())
