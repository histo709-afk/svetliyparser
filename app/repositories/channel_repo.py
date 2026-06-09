from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.channel import DestinationChannel, SourceChannel


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- SourceChannel ----

    async def get_source_by_telegram_id(
        self, telegram_id: int
    ) -> Optional[SourceChannel]:
        result = await self.session.execute(
            select(SourceChannel).where(SourceChannel.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_source_by_id(self, source_id: int) -> Optional[SourceChannel]:
        result = await self.session.execute(
            select(SourceChannel).where(SourceChannel.id == source_id)
        )
        return result.scalar_one_or_none()

    async def list_active_sources(self) -> List[SourceChannel]:
        result = await self.session.execute(
            select(SourceChannel).where(SourceChannel.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def list_all_sources(self) -> List[SourceChannel]:
        result = await self.session.execute(select(SourceChannel))
        return list(result.scalars().all())

    async def add_source(
        self, telegram_id: int, username: Optional[str], title: Optional[str]
    ) -> SourceChannel:
        channel = SourceChannel(
            telegram_id=telegram_id, username=username, title=title
        )
        self.session.add(channel)
        await self.session.flush()
        await self.session.refresh(channel)
        return channel

    async def deactivate_source(self, telegram_id: int) -> bool:
        channel = await self.get_source_by_telegram_id(telegram_id)
        if channel is None:
            return False
        channel.is_active = False
        await self.session.flush()
        return True

    # ---- DestinationChannel ----

    async def get_destination_by_telegram_id(
        self, telegram_id: int
    ) -> Optional[DestinationChannel]:
        result = await self.session.execute(
            select(DestinationChannel).where(
                DestinationChannel.telegram_id == telegram_id
            )
        )
        return result.scalar_one_or_none()

    async def get_destination_by_id(
        self, dest_id: int
    ) -> Optional[DestinationChannel]:
        result = await self.session.execute(
            select(DestinationChannel).where(DestinationChannel.id == dest_id)
        )
        return result.scalar_one_or_none()

    async def list_active_destinations(self) -> List[DestinationChannel]:
        result = await self.session.execute(
            select(DestinationChannel).where(DestinationChannel.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def list_all_destinations(self) -> List[DestinationChannel]:
        result = await self.session.execute(select(DestinationChannel))
        return list(result.scalars().all())

    async def add_destination(
        self, telegram_id: int, username: Optional[str], title: Optional[str]
    ) -> DestinationChannel:
        channel = DestinationChannel(
            telegram_id=telegram_id, username=username, title=title
        )
        self.session.add(channel)
        await self.session.flush()
        await self.session.refresh(channel)
        return channel

    async def deactivate_destination(self, telegram_id: int) -> bool:
        channel = await self.get_destination_by_telegram_id(telegram_id)
        if channel is None:
            return False
        channel.is_active = False
        await self.session.flush()
        return True
