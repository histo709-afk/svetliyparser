"""Low-level message forwarding via Telethon."""
from __future__ import annotations

from typing import List, Optional

import structlog
from telethon import TelegramClient
from telethon.tl.types import Message

log = structlog.get_logger(__name__)


async def forward_message(
    client: TelegramClient,
    message: Message,
    dest_channel_id: int,
) -> Optional[int]:
    """Forward a single message to a destination channel via native forward."""
    try:
        result = await client.forward_messages(
            entity=dest_channel_id,
            messages=message.id,
            from_peer=message.peer_id,
        )
        if isinstance(result, list):
            return result[0].id if result else None
        return result.id
    except Exception as exc:
        log.error(
            "forward_message_failed",
            dest=dest_channel_id,
            msg_id=message.id,
            error=str(exc),
        )
        return None


async def forward_album(
    client: TelegramClient,
    messages: List[Message],
    dest_channel_id: int,
) -> List[int]:
    """Forward a media group (album) to a destination channel via native forward."""
    if not messages:
        return []

    messages = sorted(messages, key=lambda m: m.id)
    try:
        result = await client.forward_messages(
            entity=dest_channel_id,
            messages=[m.id for m in messages],
            from_peer=messages[0].peer_id,
        )
        if isinstance(result, list):
            return [m.id for m in result]
        return [result.id]
    except Exception as exc:
        log.error(
            "forward_album_failed",
            dest=dest_channel_id,
            group_size=len(messages),
            error=str(exc),
        )
        return []
