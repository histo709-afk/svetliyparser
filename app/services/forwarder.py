"""Low-level message forwarding via Telethon."""
from __future__ import annotations

import asyncio
from typing import List, Optional

import structlog
from telethon import TelegramClient
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import Message

log = structlog.get_logger(__name__)


async def forward_message(
    client: TelegramClient,
    message: Message,
    dest_channel_id: int,
) -> Optional[int]:
    """Forward a single message to a destination channel via native forward.

    Returns the destination message ID, or None on failure.
    """
    try:
        result = await client(
            ForwardMessagesRequest(
                from_peer=message.peer_id,
                id=[message.id],
                to_peer=dest_channel_id,
                drop_author=False,
                noforwards=False,
            )
        )
        # result.updates contains the new message
        for update in result.updates:
            if hasattr(update, "id"):
                return update.id
        # fallback: parse from result.messages
        if hasattr(result, "messages") and result.messages:
            return result.messages[0].id
        return None
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
    """Forward a media group (album) to a destination channel via native forward.

    Returns list of destination message IDs.
    """
    if not messages:
        return []

    messages = sorted(messages, key=lambda m: m.id)
    try:
        result = await client(
            ForwardMessagesRequest(
                from_peer=messages[0].peer_id,
                id=[m.id for m in messages],
                to_peer=dest_channel_id,
                drop_author=False,
                noforwards=False,
            )
        )
        ids = []
        for update in result.updates:
            if hasattr(update, "id"):
                ids.append(update.id)
        if not ids and hasattr(result, "messages") and result.messages:
            ids = [m.id for m in result.messages]
        return ids
    except Exception as exc:
        log.error(
            "forward_album_failed",
            dest=dest_channel_id,
            group_size=len(messages),
            error=str(exc),
        )
        return []
