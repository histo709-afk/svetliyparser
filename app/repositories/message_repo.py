from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import SyncedMessage


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_copies(
        self, source_channel_id: int, source_message_id: int
    ) -> List[SyncedMessage]:
        result = await self.session.execute(
            select(SyncedMessage).where(
                SyncedMessage.source_channel_id == source_channel_id,
                SyncedMessage.source_message_id == source_message_id,
            )
        )
        return list(result.scalars().all())

    async def find_copy_for_dest(
        self,
        source_channel_id: int,
        source_message_id: int,
        dest_channel_id: int,
    ) -> Optional[SyncedMessage]:
        result = await self.session.execute(
            select(SyncedMessage).where(
                SyncedMessage.source_channel_id == source_channel_id,
                SyncedMessage.source_message_id == source_message_id,
                SyncedMessage.dest_channel_id == dest_channel_id,
            )
        )
        return result.scalar_one_or_none()

    async def save(
        self,
        source_channel_id: int,
        source_message_id: int,
        dest_channel_id: int,
        dest_message_id: int,
        media_group_id: Optional[str] = None,
    ) -> SyncedMessage:
        msg = SyncedMessage(
            source_channel_id=source_channel_id,
            source_message_id=source_message_id,
            dest_channel_id=dest_channel_id,
            dest_message_id=dest_message_id,
            media_group_id=media_group_id,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def count_today(self) -> int:
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        result = await self.session.execute(
            select(func.count(SyncedMessage.id)).where(
                SyncedMessage.synced_at >= today_start
            )
        )
        return result.scalar_one() or 0
