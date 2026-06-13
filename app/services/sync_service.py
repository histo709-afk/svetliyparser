"""Core sync service: handles new and edited messages from source channels."""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

import structlog
from telethon import TelegramClient
from telethon.tl.types import Message

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.route_repo import RouteRepository
from app.services.forwarder import forward_album, forward_message

log = structlog.get_logger(__name__)


def _channel_link(chat_id: int, msg_id: int) -> str:
    """Build t.me/c/... link for a channel message."""
    cid = abs(chat_id)
    if str(cid).startswith("100"):
        cid = int(str(cid)[3:])
    return f"https://t.me/c/{cid}/{msg_id}"


async def _send_notification(
    client: TelegramClient,
    source_title: str,
    source_id: int,
    source_msg_id: int,
    dest_title: str,
    dest_id: int,
    dest_msg_id: int,
) -> None:
    from app.config import settings
    chat_id = settings.NOTIFICATIONS_CHAT_ID
    if not chat_id:
        return
    src_link = _channel_link(source_id, source_msg_id)
    dst_link = _channel_link(dest_id, dest_msg_id)
    text = (
        f"**{source_title}** → **{dest_title}**\n"
        f"Пост №{source_msg_id} ([ссылка]({src_link}))\n"
        f"✅ Переслан: [ссылка]({dst_link})"
    )
    try:
        await client.send_message(chat_id, text, link_preview=False)
    except Exception as exc:
        log.warning("notification_failed", error=str(exc))


# In-memory buffer for media groups: {(source_channel_id, grouped_id): [Message, ...]}
_album_buffer: Dict[Tuple[int, str], List[Message]] = {}
_album_timers: Dict[Tuple[int, str], asyncio.TimerHandle] = {}

# Redis key for error log
ERRORS_KEY = "sync:errors"
MAX_ERRORS = 100


async def _get_redis():
    """Lazy import to avoid circular dependencies."""
    from app.config import settings
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


async def _log_error(message: str) -> None:
    try:
        r = await _get_redis()
        await r.lpush(ERRORS_KEY, message)
        await r.ltrim(ERRORS_KEY, 0, MAX_ERRORS - 1)
        await r.aclose()
    except Exception:
        pass  # Redis failure must not break sync


async def handle_new_message(
    event,
    telethon_client: TelegramClient,
) -> None:
    """Entry point for new messages from monitored channels."""
    message: Message = event.message
    source_channel_id: int = event.chat_id

    grouped_id: Optional[str] = (
        str(message.grouped_id) if message.grouped_id else None
    )

    if grouped_id is not None:
        # Buffer album messages and process after 1s
        key = (source_channel_id, grouped_id)
        if key not in _album_buffer:
            _album_buffer[key] = []
        _album_buffer[key].append(message)

        # Cancel existing timer and reset
        if key in _album_timers:
            _album_timers[key].cancel()

        loop = asyncio.get_event_loop()
        handle = loop.call_later(
            1.0,
            lambda k=key, c=telethon_client: asyncio.ensure_future(
                _flush_album(k, c)
            ),
        )
        _album_timers[key] = handle
    else:
        await _process_single_message(message, source_channel_id, telethon_client)


async def _flush_album(
    key: Tuple[int, str],
    telethon_client: TelegramClient,
) -> None:
    """Send buffered album messages to all destinations."""
    messages = _album_buffer.pop(key, [])
    _album_timers.pop(key, None)

    if not messages:
        return

    source_channel_id, grouped_id = key
    log.info(
        "flushing_album",
        source=source_channel_id,
        group=grouped_id,
        count=len(messages),
    )

    async with async_session_factory() as session:
        try:
            channel_repo = ChannelRepository(session)
            route_repo = RouteRepository(session)
            msg_repo = MessageRepository(session)

            source = await channel_repo.get_source_by_telegram_id(source_channel_id)
            if source is None or not source.is_active:
                return

            routes = await route_repo.list_routes_for_source(source.id)
            if not routes:
                return

            first_msg_id = messages[0].id

            for route in routes:
                dest = route.destination
                if dest is None or not dest.is_active:
                    continue

                # Dedup check (use first message of album)
                existing = await msg_repo.find_copy_for_dest(
                    source_channel_id, first_msg_id, dest.telegram_id
                )
                if existing is not None:
                    continue

                dest_ids = await forward_album(
                    telethon_client, messages, dest.telegram_id
                )
                if not dest_ids:
                    err = f"Album forward failed: src={source_channel_id} group={grouped_id} dest={dest.telegram_id}"
                    log.error("album_forward_failed", **{"src": source_channel_id, "group": grouped_id, "dest": dest.telegram_id})
                    await _log_error(err)
                    continue

                for i, (orig_msg, dest_id) in enumerate(
                    zip(messages, dest_ids)
                ):
                    await msg_repo.save(
                        source_channel_id=source_channel_id,
                        source_message_id=orig_msg.id,
                        dest_channel_id=dest.telegram_id,
                        dest_message_id=dest_id,
                        media_group_id=grouped_id,
                    )

            await session.commit()
        except Exception as exc:
            log.error("flush_album_error", error=str(exc))
            await session.rollback()
            await _log_error(f"flush_album_error: {exc}")


async def _process_single_message(
    message: Message,
    source_channel_id: int,
    telethon_client: TelegramClient,
) -> None:
    async with async_session_factory() as session:
        try:
            channel_repo = ChannelRepository(session)
            route_repo = RouteRepository(session)
            msg_repo = MessageRepository(session)

            source = await channel_repo.get_source_by_telegram_id(source_channel_id)
            if source is None or not source.is_active:
                return

            routes = await route_repo.list_routes_for_source(source.id)
            if not routes:
                return

            for route in routes:
                dest = route.destination
                if dest is None or not dest.is_active:
                    continue

                existing = await msg_repo.find_copy_for_dest(
                    source_channel_id, message.id, dest.telegram_id
                )
                if existing is not None:
                    log.debug(
                        "skipping_duplicate",
                        src_msg=message.id,
                        dest=dest.telegram_id,
                    )
                    continue

                dest_msg_id = await forward_message(
                    telethon_client, message, dest.telegram_id
                )
                if dest_msg_id is None:
                    err = f"Forward failed: src_channel={source_channel_id} src_msg={message.id} dest={dest.telegram_id}"
                    await _log_error(err)
                    continue

                await msg_repo.save(
                    source_channel_id=source_channel_id,
                    source_message_id=message.id,
                    dest_channel_id=dest.telegram_id,
                    dest_message_id=dest_msg_id,
                )
                await _send_notification(
                    telethon_client,
                    source.title or str(source_channel_id),
                    source_channel_id,
                    message.id,
                    dest.title or str(dest.telegram_id),
                    dest.telegram_id,
                    dest_msg_id,
                )

            await session.commit()
        except Exception as exc:
            log.error("process_message_error", error=str(exc))
            await session.rollback()
            await _log_error(f"process_message_error: {exc}")


async def handle_edited_message(
    event,
    telethon_client: TelegramClient,
) -> None:
    """Edit all synced copies when a source message is edited."""
    message: Message = event.message
    source_channel_id: int = event.chat_id

    async with async_session_factory() as session:
        try:
            msg_repo = MessageRepository(session)
            copies = await msg_repo.find_copies(source_channel_id, message.id)
            if not copies:
                return

            text = message.message or ""
            entities = message.entities or []

            for copy in copies:
                try:
                    await asyncio.sleep(0.3)
                    await telethon_client.edit_message(
                        entity=copy.dest_channel_id,
                        message=copy.dest_message_id,
                        text=text,
                        formatting_entities=entities if entities else None,
                    )
                except Exception as exc:
                    if "not modified" in str(exc).lower():
                        pass  # content unchanged, ignore
                    else:
                        err = f"Edit failed: dest={copy.dest_channel_id} msg={copy.dest_message_id}: {exc}"
                        log.warning("edit_copy_failed", error=str(exc))
                        await _log_error(err)

        except Exception as exc:
            log.error("handle_edit_error", error=str(exc))
            await _log_error(f"handle_edit_error: {exc}")


async def get_last_errors(n: int = 10) -> List[str]:
    """Fetch last N errors from Redis."""
    try:
        r = await _get_redis()
        errors = await r.lrange(ERRORS_KEY, 0, n - 1)
        await r.aclose()
        return errors
    except Exception:
        return ["Redis unavailable"]
