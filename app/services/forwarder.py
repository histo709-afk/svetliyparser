"""Copy messages from source to destination: download via Telethon, send via Bot API."""
from __future__ import annotations

from typing import List, Optional

import structlog
from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import MessageEntity as AiogramMessageEntity

log = structlog.get_logger(__name__)


def _get_bot() -> Bot:
    from app.config import settings
    return Bot(token=settings.BOT_TOKEN)


CAPTION_LIMIT = 1024  # Telegram's max caption length for photo/video/document


def _truncate_caption(text: Optional[str]) -> Optional[str]:
    """Telegram rejects the whole send if a media caption exceeds 1024 chars
    (unlike a plain text message, capped at 4096) — truncate instead of
    losing the post entirely."""
    if not text or len(text) <= CAPTION_LIMIT:
        return text
    return text[:CAPTION_LIMIT - 1].rstrip() + "…"


# Telethon entity class name -> Bot API entity type. Types needing extra
# Telegram objects we don't carry over here (text_mention's full User,
# custom_emoji's document id) are simply skipped rather than guessed at.
_ENTITY_TYPE_MAP = {
    "MessageEntityBold": "bold",
    "MessageEntityItalic": "italic",
    "MessageEntityUnderline": "underline",
    "MessageEntityStrike": "strikethrough",
    "MessageEntitySpoiler": "spoiler",
    "MessageEntityCode": "code",
    "MessageEntityUrl": "url",
    "MessageEntityMention": "mention",
    "MessageEntityHashtag": "hashtag",
    "MessageEntityCashtag": "cashtag",
    "MessageEntityBotCommand": "bot_command",
    "MessageEntityEmail": "email",
    "MessageEntityPhone": "phone_number",
    "MessageEntityBlockquote": "blockquote",
}


def convert_entities(telethon_entities, cutoff: int) -> Optional[List[AiogramMessageEntity]]:
    """Convert Telethon formatting entities to aiogram's MessageEntity,
    keeping only those that fit entirely within the surviving text (offsets
    are UTF-16 code units, matching Telegram's own convention, so a plain
    Python len() cutoff would be wrong whenever the kept text contains
    emoji/astral characters — cutoff must already be computed the same
    surrogate-aware way, see sync_service's use of add_surrogate)."""
    if not telethon_entities:
        return None
    result: List[AiogramMessageEntity] = []
    for e in telethon_entities:
        if e.offset + e.length > cutoff:
            continue
        cls_name = type(e).__name__
        if cls_name == "MessageEntityTextUrl":
            result.append(AiogramMessageEntity(type="text_link", offset=e.offset, length=e.length, url=e.url))
            continue
        if cls_name == "MessageEntityPre":
            result.append(AiogramMessageEntity(
                type="pre", offset=e.offset, length=e.length,
                language=getattr(e, "language", None) or None,
            ))
            continue
        bot_type = _ENTITY_TYPE_MAP.get(cls_name)
        if bot_type:
            result.append(AiogramMessageEntity(type=bot_type, offset=e.offset, length=e.length))
    return result or None



def convert_reply_markup(telethon_reply_markup) -> Optional[InlineKeyboardMarkup]:
    """Convert a Telethon inline keyboard (e.g. a "Проложить маршрут" map-link
    button) to aiogram's InlineKeyboardMarkup. Many source posts put their
    hyperlink on a URL button rather than as a text formatting entity, so
    without this the link is silently dropped even though the caption text
    (e.g. "Проложить маршрут") still gets copied — only url buttons are kept,
    since callback/login/other button types wouldn't work pointed at a
    different bot anyway."""
    rows = getattr(telethon_reply_markup, "rows", None)
    if not rows:
        return None
    keyboard: List[List[InlineKeyboardButton]] = []
    for row in rows:
        buttons = []
        for btn in getattr(row, "buttons", None) or []:
            url = getattr(btn, "url", None)
            text = getattr(btn, "text", None)
            if url and text:
                buttons.append(InlineKeyboardButton(text=text, url=url))
        if buttons:
            keyboard.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None


async def send_message(
    client,
    message,
    dest_channel_id: int,
    override_text: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    entities: Optional[List[AiogramMessageEntity]] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[int]:
    """Copy a single message (text / photo / video) to dest via Bot API.
    Falls back to sending without the reply link if the replied-to message
    is gone (deleted/invalid) so a stale thread link never blocks the post.
    `entities` (already converted + cutoff-filtered by the caller) preserves
    formatting/hyperlinks from the source post — pass None to send as plain
    text (the caller's job to decide when offsets are still valid)."""
    result = await _send_message_impl(client, message, dest_channel_id, override_text, reply_to_message_id, entities, reply_markup)
    if result is None and reply_to_message_id is not None:
        log.warning("send_message_reply_fallback", dest=dest_channel_id, msg_id=message.id)
        result = await _send_message_impl(client, message, dest_channel_id, override_text, None, entities, reply_markup)
    return result


async def _send_message_impl(
    client,
    message,
    dest_channel_id: int,
    override_text: Optional[str],
    reply_to_message_id: Optional[int],
    entities: Optional[List[AiogramMessageEntity]] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Optional[int]:
    bot = _get_bot()
    # Entities and parse_mode are mutually exclusive on Telegram's side —
    # explicitly clear the bot's default (HTML) parse mode whenever real
    # entities are supplied, otherwise Bot API would try to HTML-parse the
    # plain text (mangling any literal <, >, & in it) instead of honoring
    # the entities.
    parse_mode = None if entities else "HTML"
    try:
        text = override_text if override_text is not None else (message.message or message.text or "")
        media = getattr(message, "media", None)

        if media is None:
            result = await bot.send_message(
                chat_id=dest_channel_id,
                text=text or ".",
                reply_to_message_id=reply_to_message_id,
                entities=entities,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            return result.message_id

        from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

        if isinstance(media, MessageMediaPhoto):
            data = await client.download_media(message, bytes)
            result = await bot.send_photo(
                chat_id=dest_channel_id,
                photo=BufferedInputFile(data, "photo.jpg"),
                caption=_truncate_caption(text) or None,
                caption_entities=entities,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
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
                    caption=_truncate_caption(text) or None,
                    caption_entities=entities,
                    parse_mode=parse_mode,
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup,
                )
            else:
                result = await bot.send_document(
                    chat_id=dest_channel_id,
                    document=BufferedInputFile(data, filename or "file"),
                    caption=_truncate_caption(text) or None,
                    caption_entities=entities,
                    parse_mode=parse_mode,
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup,
                )
            return result.message_id

        # Fallback: send as document
        data = await client.download_media(message, bytes)
        if data:
            result = await bot.send_document(
                chat_id=dest_channel_id,
                document=BufferedInputFile(data, "file"),
                caption=_truncate_caption(text) or None,
                caption_entities=entities,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_message_id,
                reply_markup=reply_markup,
            )
            return result.message_id

        if text:
            result = await bot.send_message(
                chat_id=dest_channel_id, text=text, reply_to_message_id=reply_to_message_id,
                entities=entities, parse_mode=parse_mode, reply_markup=reply_markup,
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
                cap = _truncate_caption(override_caption) if override_caption else None
                caption_used = True
            else:
                text = msg.message or ""
                cap = _truncate_caption(text) if not caption_used and text else None
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
