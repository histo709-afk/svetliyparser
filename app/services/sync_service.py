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
from app.services.forwarder import send_album, send_message

log = structlog.get_logger(__name__)


async def _is_banned(text: str, route_id: int) -> bool:
    """Check if message text contains any banned word for this route."""
    if not text:
        return False
    from app.repositories.banned_word_repo import BannedWordRepository
    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        words = await repo.get_for_check(route_id)
    text_lower = text.lower()
    return any(w in text_lower for w in words)


async def _apply_replacements(text: str, route_id: int) -> str:
    """Apply text replacement rules (global + route-specific) to message text."""
    if not text:
        return text
    from app.repositories.text_replacement_repo import TextReplacementRepository
    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        rules = await repo.get_for_apply(route_id)
    for find_text, replace_with in rules:
        text = text.replace(find_text, replace_with)
    return text


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
                log.warning("album_source_not_found", source_channel_id=source_channel_id)
                return

            routes = await route_repo.list_routes_for_source(source.id)
            if not routes:
                log.warning("album_no_routes", source_id=source.id)
                return

            first_msg_id = messages[0].id

            active_routes = [
                r for r in routes
                if r.destination is not None and r.destination.is_active
            ]

            dests_to_forward = []
            for route in active_routes:
                existing = await msg_repo.find_copy_for_dest(
                    source_channel_id, first_msg_id, route.destination.telegram_id
                )
                if existing is None:
                    dests_to_forward.append(route)

            log.info("album_forwarding", source_id=source.id, dests=len(dests_to_forward))

            async def _forward_album_one(route):
                dest = route.destination
                dest_ids = await send_album(
                    telethon_client, messages, dest.telegram_id,
                )
                if not dest_ids:
                    err = f"Album forward failed: src={source_channel_id} group={grouped_id} dest={dest.telegram_id}"
                    log.error("album_forward_failed", src=source_channel_id, group=grouped_id, dest=dest.telegram_id)
                    await _log_error(err)
                    return
                for orig_msg, dest_id in zip(messages, dest_ids):
                    await msg_repo.save(
                        source_channel_id=source_channel_id,
                        source_message_id=orig_msg.id,
                        dest_channel_id=dest.telegram_id,
                        dest_message_id=dest_id,
                        media_group_id=grouped_id,
                    )

            await asyncio.gather(*[_forward_album_one(r) for r in dests_to_forward])
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
                log.warning("source_not_found_or_inactive", source_channel_id=source_channel_id)
                return

            routes = await route_repo.list_routes_for_source(source.id)
            if not routes:
                log.warning("no_routes_for_source", source_id=source.id)
                return

            active_routes = [
                r for r in routes
                if r.destination is not None and r.destination.is_active
            ]
            log.info("processing_message", source_id=source.id, routes=len(active_routes))

            # Dedup check
            dests_to_forward = []
            for route in active_routes:
                existing = await msg_repo.find_copy_for_dest(
                    source_channel_id, message.id, route.destination.telegram_id
                )
                if existing is None:
                    dests_to_forward.append(route)

            if not dests_to_forward:
                return

            # Forward to all destinations in parallel
            async def _forward_one(route):
                dest = route.destination
                msg_text = message.message or message.text or ""
                if await _is_banned(msg_text, route.id):
                    log.info("message_banned", src=source_channel_id, msg=message.id, dest=dest.telegram_id)
                    return
                msg_text = await _apply_replacements(msg_text, route.id)
                log.info("sending_message", src=source_channel_id, msg=message.id, dest=dest.telegram_id)
                dest_msg_id = await send_message(
                    telethon_client, message, dest.telegram_id, override_text=msg_text,
                )
                if dest_msg_id is None:
                    err = f"Forward failed: src_channel={source_channel_id} src_msg={message.id} dest={dest.telegram_id}"
                    log.error("forward_failed", src=source_channel_id, msg=message.id, dest=dest.telegram_id)
                    await _log_error(err)
                    return
                log.info("message_sent", src=source_channel_id, msg=message.id, dest=dest.telegram_id, dest_msg=dest_msg_id)
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

            await asyncio.gather(*[_forward_one(r) for r in dests_to_forward])
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


# {source_channel_id: last_processed_message_id}
_last_seen: Dict[int, int] = {}

POLL_INTERVAL = 30  # seconds


async def _init_last_seen(client: TelegramClient) -> None:
    """On startup, record the latest message ID for every source channel
    so we only forward posts that appear AFTER the bot starts."""
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()

    log.info("init_last_seen_start", count=len(sources))
    for source in sources:
        try:
            msgs = await client.get_messages(source.telegram_id, limit=1)
            if msgs:
                _last_seen[source.telegram_id] = msgs[0].id
            await asyncio.sleep(0.1)
        except ValueError:
            # Channel not accessible (not joined, banned, etc.) — skip silently
            _last_seen[source.telegram_id] = 0
        except Exception:
            pass
    log.info("init_last_seen_done", channels=len(_last_seen))


async def poll_sources(client: TelegramClient) -> None:
    """
    Periodically poll all active source channels for new messages.
    This is the primary delivery mechanism — push updates are unreliable
    for accounts subscribed to many channels.
    """
    await _init_last_seen(client)
    log.info("poll_loop_started", interval=POLL_INTERVAL)
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            async with async_session_factory() as session:
                channel_repo = ChannelRepository(session)
                sources = await channel_repo.list_active_sources()

            for source in sources:
                try:
                    await _poll_one(client, source.telegram_id)
                    await asyncio.sleep(0.3)
                except ValueError as exc:
                    # Channel inaccessible (not joined, deleted, etc.) — log once, skip
                    log.warning("poll_one_inaccessible", source=source.telegram_id, error=str(exc)[:120])
                except Exception as exc:
                    log.warning("poll_one_error", source=source.telegram_id, error=str(exc)[:80])
        except Exception as exc:
            log.error("poll_loop_error", error=str(exc))


async def _poll_one(client: TelegramClient, source_channel_id: int) -> None:
    """Fetch recent messages from one source channel and process any new ones."""
    last_id = _last_seen.get(source_channel_id, 0)

    messages = await client.get_messages(source_channel_id, limit=5, min_id=last_id)
    if not messages:
        return

    # Group by grouped_id (albums)
    singles: List[Message] = []
    albums: Dict[str, List[Message]] = {}

    for msg in messages:
        if msg.id > _last_seen.get(source_channel_id, 0):
            _last_seen[source_channel_id] = msg.id

        gid = str(msg.grouped_id) if getattr(msg, "grouped_id", None) else None
        if gid:
            albums.setdefault(gid, []).append(msg)
        else:
            singles.append(msg)

    for msg in singles:
        await _process_single_message(msg, source_channel_id, client)

    for gid, msgs in albums.items():
        await _process_album_poll(msgs, source_channel_id, gid, client)


async def _process_album_poll(
    messages: List[Message],
    source_channel_id: int,
    grouped_id: str,
    client: TelegramClient,
) -> None:
    """Process a polled album — same logic as _flush_album but without buffering."""
    messages = sorted(messages, key=lambda m: m.id)
    async with async_session_factory() as session:
        try:
            channel_repo = ChannelRepository(session)
            route_repo = RouteRepository(session)
            msg_repo = MessageRepository(session)

            source = await channel_repo.get_source_by_telegram_id(source_channel_id)
            if source is None or not source.is_active:
                return

            routes = await route_repo.list_routes_for_source(source.id)
            active_routes = [r for r in routes if r.destination and r.destination.is_active]
            first_msg_id = messages[0].id

            dests_to_forward = []
            for route in active_routes:
                existing = await msg_repo.find_copy_for_dest(
                    source_channel_id, first_msg_id, route.destination.telegram_id
                )
                if existing is None:
                    dests_to_forward.append(route)

            if not dests_to_forward:
                return

            log.info("poll_album_forwarding", source=source_channel_id, group=grouped_id, dests=len(dests_to_forward))

            async def _fwd(route):
                dest = route.destination
                first_text = messages[0].message or messages[0].text or "" if messages else ""
                if await _is_banned(first_text, route.id):
                    log.info("album_banned", src=source_channel_id, group=grouped_id, dest=dest.telegram_id)
                    return
                first_text = await _apply_replacements(first_text, route.id)
                dest_ids = await send_album(client, messages, dest.telegram_id, override_caption=first_text)
                if not dest_ids:
                    log.error("poll_album_failed", src=source_channel_id, dest=dest.telegram_id)
                    return
                for orig_msg, dest_id in zip(messages, dest_ids):
                    await msg_repo.save(
                        source_channel_id=source_channel_id,
                        source_message_id=orig_msg.id,
                        dest_channel_id=dest.telegram_id,
                        dest_message_id=dest_id,
                        media_group_id=grouped_id,
                    )
                log.info("poll_album_sent", src=source_channel_id, dest=dest.telegram_id, count=len(dest_ids))

            await asyncio.gather(*[_fwd(r) for r in dests_to_forward])
            await session.commit()
        except Exception as exc:
            log.error("poll_album_error", error=str(exc))
            await session.rollback()


async def get_last_errors(n: int = 10) -> List[str]:
    """Fetch last N errors from Redis."""
    try:
        r = await _get_redis()
        errors = await r.lrange(ERRORS_KEY, 0, n - 1)
        await r.aclose()
        return errors
    except Exception:
        return ["Redis unavailable"]
