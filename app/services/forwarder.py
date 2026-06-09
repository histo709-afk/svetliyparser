"""Low-level message forwarding via Telethon."""
from __future__ import annotations

import asyncio
from typing import List, Optional

import structlog
from telethon import TelegramClient
from telethon.tl.types import (
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaPoll,
    InputMediaPoll,
)

log = structlog.get_logger(__name__)

# Rate limiting delay between sends (seconds)
SEND_DELAY = 0.4


async def forward_message(
    client: TelegramClient,
    message: Message,
    dest_channel_id: int,
) -> Optional[int]:
    """Forward a single message to a destination channel.

    Returns the destination message ID, or None on failure.
    """
    await asyncio.sleep(SEND_DELAY)
    try:
        text = message.message or ""
        entities = message.entities or []

        if message.media is None:
            # Pure text message
            sent = await client.send_message(
                entity=dest_channel_id,
                message=text,
                formatting_entities=entities if entities else None,
                link_preview=False,
            )
            return sent.id

        if isinstance(message.media, MessageMediaPoll):
            # Polls cannot be forwarded directly — re-create them
            poll = message.media.poll
            results = message.media.results
            try:
                sent = await client.send_message(
                    entity=dest_channel_id,
                    message=InputMediaPoll(poll=poll),
                )
                return sent.id
            except Exception as exc:
                log.warning("poll_forward_failed", error=str(exc))
                # Fall back to text
                poll_text = f"📊 {poll.question.text}\n" + "\n".join(
                    f"• {a.text.text}" for a in poll.answers
                )
                sent = await client.send_message(
                    entity=dest_channel_id,
                    message=poll_text,
                )
                return sent.id

        # Photo / Video / Document / Audio / Voice / Sticker — use send_file
        sent = await client.send_file(
            entity=dest_channel_id,
            file=message.media,
            caption=text,
            formatting_entities=entities if entities else None,
        )
        if isinstance(sent, list):
            return sent[0].id
        return sent.id

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
    """Forward a media group (album) to a destination channel.

    Returns list of destination message IDs.
    """
    await asyncio.sleep(SEND_DELAY)
    if not messages:
        return []

    try:
        # Sort by ID to preserve order
        messages = sorted(messages, key=lambda m: m.id)
        files = [m.media for m in messages if m.media is not None]
        if not files:
            return []

        # Use caption from first message with text
        caption = next((m.message for m in messages if m.message), "")
        entities = next((m.entities for m in messages if m.entities), None)

        sent = await client.send_file(
            entity=dest_channel_id,
            file=files,
            caption=caption,
            formatting_entities=entities,
        )
        if isinstance(sent, list):
            return [m.id for m in sent]
        return [sent.id]

    except Exception as exc:
        log.error(
            "forward_album_failed",
            dest=dest_channel_id,
            group_size=len(messages),
            error=str(exc),
        )
        # Try forwarding individually as fallback
        ids = []
        for msg in messages:
            mid = await forward_message(client, msg, dest_channel_id)
            if mid is not None:
                ids.append(mid)
        return ids
