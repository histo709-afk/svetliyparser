"""Copy messages from source to destination: download via Telethon, send via Bot API."""
from __future__ import annotations

from typing import List, Optional

import structlog
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo

log = structlog.get_logger(__name__)


def _get_bot() -> Bot:
    from app.config import settings
    return Bot(token=settings.BOT_TOKEN)



async def send_message(
    client,
    message,
    dest_channel_id: int,
    override_text: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> Optional[int]:
    """Copy a single message (text / photo / video) to dest via Bot API.
    Falls back to sending without the reply link if the replied-to message
    is gone (deleted/invalid) so a stale thread link never blocks the post."""
    result = await _send_message_impl(client, message, dest_channel_id, override_text, reply_to_message_id)
    if result is None and reply_to_message_id is not None:
        log.warning("send_message_reply_fallback", dest=dest_channel_id, msg_id=message.id)
        result = await _send_message_impl(client, message, dest_channel_id, override_text, None)
    return result


async def _send_message_impl(
    client,
    message,
    dest_channel_id: int,
    override_text: Optional[str],
    reply_to_message_id: Optional[int],
) -> Optional[int]:
    bot = _get_bot()
    try:
        text = override_text if override_text is not None else (message.message or message.text or "")
        media = getattr(message, "media", None)

        if media is None:
            result = await bot.send_message(
                chat_id=dest_channel_id,
                text=text or ".",
                reply_to_message_id=reply_to_message_id,
            )
            return result.message_id

        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

        if isinstance(media, MessageMediaPhoto):
            data = await client.download_media(message, bytes)
            result = await bot.send_photo(
                chat_id=dest_channel_id,
                photo=BufferedInputFile(data, "photo.jpg"),
                caption=text or None,
                reply_to_message_id=reply_to_message_id,
            )
            return result.message_id

        if isinstance(media, MessageMediaDocument):
            doc = media.document
            attrs = {type(a).__name__: a for a in (doc.attributes or [])}
            is_video = "DocumentAttributeVideo" in attrs

            data = await client.download_media(message, bytes)
            filename = getattr(attrs.get("DocumentAttributeFilename"), "file_name", None)

            if is_video:
                result = await bot.send_video(
                    chat_id=dest_channel_id,
                    video=BufferedInputFile(data, filename or "video.mp4"),
                    caption=text or None,
                    reply_to_message_id=reply_to_message_id,
                )
            else:
                result = await bot.send_document(
                    chat_id=dest_channel_id,
                    document=BufferedInputFile(data, filename or "file"),
                    caption=text or None,
                    reply_to_message_id=reply_to_message_id,
                )
            return result.message_id

        # Fallback: send as document
        data = await client.download_media(message, bytes)
        if data:
            result = await bot.send_document(
                chat_id=dest_channel_id,
                document=BufferedInputFile(data, "file"),
                caption=text or None,
                reply_to_message_id=reply_to_message_id,
            )
            return result.message_id

        if text:
            result = await bot.send_message(
                chat_id=dest_channel_id, text=text, reply_to_message_id=reply_to_message_id,
            )
            return result.message_id

        log.warning("send_message_nothing_to_send", dest=dest_channel_id, msg_id=message.id)
        return None

    except Exception as exc:
        log.error("send_message_failed", dest=dest_channel_id, msg_id=message.id, error=str(exc))
        return None
    finally:
        await bot.session.close()


async def send_album(
    client,
    messages: List,
    dest_channel_id: int,
    override_caption: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
) -> List[int]:
    """Copy a media group (album) to dest via Bot API send_media_group.
    Falls back to sending without the reply link if the replied-to message
    is gone (deleted/invalid) so a stale thread link never blocks the album."""
    result = await _send_album_impl(client, messages, dest_channel_id, override_caption, reply_to_message_id)
    if not result and reply_to_message_id is not None:
        log.warning("send_album_reply_fallback", dest=dest_channel_id)
        result = await _send_album_impl(client, messages, dest_channel_id, override_caption, None)
    return result


async def _send_album_impl(
    client,
    messages: List,
    dest_channel_id: int,
    override_caption: Optional[str],
    reply_to_message_id: Optional[int],
) -> List[int]:
    if not messages:
        return []
    messages = sorted(messages, key=lambda m: m.id)
    bot = _get_bot()
    try:
        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

        media_items = []
        caption_used = False

        for msg in messages:
            if not caption_used and override_caption is not None:
                cap = override_caption if override_caption else None
                caption_used = True
            else:
                text = msg.message or ""
                cap = text if not caption_used and text else None
                if cap:
                    caption_used = True

            media = getattr(msg, "media", None)
            if media is None:
                continue

            if isinstance(media, MessageMediaPhoto):
                data = await client.download_media(msg, bytes)
                media_items.append(InputMediaPhoto(
                    media=BufferedInputFile(data, "photo.jpg"),
                    caption=cap,
                ))
            elif isinstance(media, MessageMediaDocument):
                doc = media.document
                attrs = {type(a).__name__: a for a in (doc.attributes or [])}
                is_video = "DocumentAttributeVideo" in attrs
                filename = getattr(attrs.get("DocumentAttributeFilename"), "file_name", None)
                data = await client.download_media(msg, bytes)
                if is_video:
                    media_items.append(InputMediaVideo(
                        media=BufferedInputFile(data, filename or "video.mp4"),
                        caption=cap,
                    ))
                else:
                    media_items.append(InputMediaPhoto(
                        media=BufferedInputFile(data, filename or "file"),
                        caption=cap,
                    ))

        if not media_items:
            # All text — send first message text
            text = messages[0].message or ""
            if text:
                result = await bot.send_message(
                    chat_id=dest_channel_id, text=text, reply_to_message_id=reply_to_message_id,
                )
                return [result.message_id]
            return []

        if len(media_items) == 1:
            # send_media_group requires >=2 items; send single
            item = media_items[0]
            if isinstance(item, InputMediaPhoto):
                result = await bot.send_photo(
                    chat_id=dest_channel_id,
                    photo=item.media,
                    caption=item.caption,
                    caption_entities=item.caption_entities,
                    reply_to_message_id=reply_to_message_id,
                )
            else:
                result = await bot.send_video(
                    chat_id=dest_channel_id,
                    video=item.media,
                    caption=item.caption,
                    caption_entities=item.caption_entities,
                    reply_to_message_id=reply_to_message_id,
                )
            return [result.message_id]

        results = await bot.send_media_group(
            chat_id=dest_channel_id,
            media=media_items,
            reply_to_message_id=reply_to_message_id,
        )
        ids = [r.message_id for r in results]
        log.info("album_sent", dest=dest_channel_id, count=len(ids))
        return ids

    except Exception as exc:
        log.error("send_album_failed", dest=dest_channel_id, error=str(exc))
        return []
    finally:
        await bot.session.close()
