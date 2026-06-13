"""Low-level message forwarding via Telethon userbot."""
from __future__ import annotations

from typing import List, Optional

import structlog
from telethon import TelegramClient
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import UpdateMessageID, UpdateNewChannelMessage, UpdateNewMessage

log = structlog.get_logger(__name__)


async def forward_message(
    client: TelegramClient,
    message,
    dest_channel_id: int,
) -> Optional[int]:
    """Forward a single message to destination channel via Telethon userbot."""
    try:
        dest_entity = await client.get_entity(dest_channel_id)
        result = await client(ForwardMessagesRequest(
            from_peer=message.peer_id,
            id=[message.id],
            to_peer=dest_entity,
            drop_author=False,
        ))
        dest_msg_id = _extract_message_id(result)
        log.info("forward_ok", dest=dest_channel_id, src_msg=message.id, dest_msg=dest_msg_id)
        return dest_msg_id or message.id
    except Exception as exc:
        log.error("forward_message_failed", dest=dest_channel_id, msg_id=message.id, error=str(exc))
        return None


async def forward_album(
    client: TelegramClient,
    messages: List,
    dest_channel_id: int,
) -> List[int]:
    """Forward album (media group) to destination channel via Telethon userbot."""
    if not messages:
        return []
    messages = sorted(messages, key=lambda m: m.id)
    try:
        dest_entity = await client.get_entity(dest_channel_id)
        result = await client(ForwardMessagesRequest(
            from_peer=messages[0].peer_id,
            id=[m.id for m in messages],
            to_peer=dest_entity,
            drop_author=False,
        ))
        ids = _extract_all_message_ids(result)
        log.info("album_forward_ok", dest=dest_channel_id, count=len(ids))
        return ids if ids else [m.id for m in messages]
    except Exception as exc:
        log.error("forward_album_failed", dest=dest_channel_id, error=str(exc))
        return []


def _extract_message_id(result) -> Optional[int]:
    for upd in getattr(result, "updates", []):
        if isinstance(upd, UpdateMessageID):
            return upd.id
        if isinstance(upd, (UpdateNewChannelMessage, UpdateNewMessage)):
            return getattr(upd.message, "id", None)
    return None


def _extract_all_message_ids(result) -> List[int]:
    ids = []
    for upd in getattr(result, "updates", []):
        if isinstance(upd, UpdateMessageID):
            ids.append(upd.id)
        elif isinstance(upd, (UpdateNewChannelMessage, UpdateNewMessage)):
            mid = getattr(upd.message, "id", None)
            if mid:
                ids.append(mid)
    return ids
