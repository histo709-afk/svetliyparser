"""Low-level message forwarding via Telegram Bot API."""
from __future__ import annotations

from typing import List, Optional

import structlog
from aiogram import Bot

log = structlog.get_logger(__name__)


def _get_bot() -> Bot:
    from app.config import settings
    return Bot(token=settings.BOT_TOKEN)


def _telethon_peer_to_chat_id(peer_id) -> int:
    """Convert Telethon PeerChannel to Bot API chat_id (-100XXXXXXXXX)."""
    cid = getattr(peer_id, "channel_id", None)
    if cid:
        return -int(f"100{cid}")
    return 0


async def forward_message(
    _client,
    message,
    dest_channel_id: int,
) -> Optional[int]:
    """Forward a single message to a destination channel via Bot API."""
    from_chat_id = _telethon_peer_to_chat_id(message.peer_id)
    bot = _get_bot()
    try:
        result = await bot.forward_message(
            chat_id=dest_channel_id,
            from_chat_id=from_chat_id,
            message_id=message.id,
        )
        log.info("forward_ok", dest=dest_channel_id, msg_id=message.id, result_id=result.message_id)
        return result.message_id
    except Exception as exc:
        log.error("forward_message_failed", dest=dest_channel_id, from_chat=from_chat_id, msg_id=message.id, error=str(exc))
        return None
    finally:
        await bot.session.close()


async def forward_album(
    _client,
    messages: List,
    dest_channel_id: int,
) -> List[int]:
    """Forward album messages via Bot API (each message individually)."""
    if not messages:
        return []
    messages = sorted(messages, key=lambda m: m.id)
    from_chat_id = _telethon_peer_to_chat_id(messages[0].peer_id)
    bot = _get_bot()
    ids = []
    try:
        for msg in messages:
            try:
                result = await bot.forward_message(
                    chat_id=dest_channel_id,
                    from_chat_id=from_chat_id,
                    message_id=msg.id,
                )
                ids.append(result.message_id)
                log.info("album_forward_ok", dest=dest_channel_id, msg_id=msg.id)
            except Exception as exc:
                log.error("forward_album_msg_failed", dest=dest_channel_id, from_chat=from_chat_id, msg_id=msg.id, error=str(exc))
    finally:
        await bot.session.close()
    return ids
