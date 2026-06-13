"""Telethon event listeners for source channel monitoring."""
from __future__ import annotations

import asyncio

import structlog
from telethon import TelegramClient, events

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services import sync_service

log = structlog.get_logger(__name__)

RELOAD_INTERVAL = 60  # seconds


async def join_missing_sources(client: TelegramClient) -> None:
    """Join all source channels that userbot is not already subscribed to."""
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.errors import UserAlreadyParticipantError, FloodWaitError

    # Get current dialog ids
    try:
        dialogs = await client.get_dialogs(limit=None)
    except Exception as exc:
        log.error("join_missing_get_dialogs_failed", error=str(exc))
        return
    dialog_ids = {d.entity.id for d in dialogs if hasattr(d, "entity")}

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()

    joined = 0
    skipped = 0
    errors = 0
    for src in sources:
        if not src.username:
            skipped += 1
            continue
        try:
            entity = await client.get_entity(f"@{src.username}")
            if entity.id in dialog_ids:
                skipped += 1
                continue
            await client(JoinChannelRequest(entity))
            joined += 1
            await asyncio.sleep(1.5)
        except UserAlreadyParticipantError:
            skipped += 1
        except FloodWaitError as e:
            log.warning("join_flood_wait", seconds=e.seconds, username=src.username)
            await asyncio.sleep(min(e.seconds, 30))
        except Exception as e:
            log.warning("join_failed", username=src.username, error=str(e)[:60])
            errors += 1

    log.info("join_missing_done", joined=joined, skipped=skipped, errors=errors)


async def fix_all_stale_ids(client: TelegramClient) -> int:
    """
    After get_dialogs(), fix all stale telegram_ids in DB by matching usernames
    from the Telethon entity cache. No API calls needed — uses local cache.
    Returns number of fixed entries.
    """
    # Build username → full_id map from entity cache
    username_to_id: dict[str, int] = {}
    try:
        dialogs = await client.get_dialogs(limit=None)
        for d in dialogs:
            entity = d.entity
            uname = getattr(entity, "username", None)
            if uname:
                eid = getattr(entity, "id", None)
                if eid:
                    full_id = -int(f"100{eid}")
                    username_to_id[uname.lower()] = full_id
        log.info("dialog_entity_cache_built", entries=len(username_to_id))
    except Exception as exc:
        log.error("fix_stale_ids_get_dialogs_failed", error=str(exc))
        return 0

    fixed = 0
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()
        for src in sources:
            if not src.username:
                continue
            correct_id = username_to_id.get(src.username.lower())
            if correct_id and src.telegram_id != correct_id:
                log.info("fixing_stale_id", username=src.username, old=src.telegram_id, new=correct_id)
                src.telegram_id = correct_id
                fixed += 1
        if fixed:
            await session.commit()

    log.info("stale_ids_fixed", count=fixed)
    return fixed


async def run_listener(client: TelegramClient) -> None:
    """Start listening for messages and periodically reload channel list."""

    known_ids: set[int] = set()
    _fixing: set[int] = set()
    _skip_ids: set[int] = set()  # chats that are not sources and never will be
    new_handler = None
    edit_handler = None

    async def _reload() -> None:
        nonlocal known_ids
        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            sources = await repo.list_active_sources()
            known_ids = {s.telegram_id for s in sources}
        log.info("sources_loaded", count=len(known_ids))

    async def _try_fix(chat_id: int, peer) -> bool:
        """Resolve unknown chat_id via Telethon entity, update DB if username matches a source."""
        if chat_id in _fixing:
            return False
        _fixing.add(chat_id)
        try:
            try:
                entity = await client.get_entity(peer if peer is not None else chat_id)
            except Exception as e:
                log.warning("fix_entity_failed", chat_id=chat_id, error=str(e))
                return False

            username = getattr(entity, "username", None)
            if not username:
                log.info("unknown_channel_no_username", chat_id=chat_id,
                         title=getattr(entity, "title", "?"))
                return False

            async with async_session_factory() as session:
                repo = ChannelRepository(session)
                sources = await repo.list_all_sources()
                for src in sources:
                    if (src.username or "").lower() == username.lower() and src.telegram_id != chat_id:
                        log.info("auto_fix_telegram_id", username=username,
                                 old=src.telegram_id, new=chat_id)
                        src.telegram_id = chat_id
                        await session.commit()
                        return True
            log.info("unknown_channel_no_match", username=username, chat_id=chat_id)
            return False
        finally:
            _fixing.discard(chat_id)

    async def register_handlers() -> None:
        nonlocal new_handler, edit_handler

        if new_handler is not None:
            client.remove_event_handler(new_handler)
        if edit_handler is not None:
            client.remove_event_handler(edit_handler)

        @client.on(events.NewMessage())
        async def on_new_message(event: events.NewMessage.Event) -> None:
            chat_id = event.chat_id
            if chat_id in _skip_ids:
                return
            if chat_id not in known_ids:
                peer = getattr(event.message, "peer_id", None)
                fixed = await _try_fix(chat_id, peer)
                if fixed:
                    await _reload()
                    known_ids.add(chat_id)
                else:
                    _skip_ids.add(chat_id)
                    return
            log.info("event_received", chat_id=chat_id, msg_id=event.message.id)
            try:
                await sync_service.handle_new_message(event, client)
            except Exception as exc:
                log.error("on_new_message_unhandled", error=str(exc))

        @client.on(events.MessageEdited())
        async def on_edited_message(event: events.MessageEdited.Event) -> None:
            if event.chat_id not in known_ids:
                return
            try:
                await sync_service.handle_edited_message(event, client)
            except Exception as exc:
                log.error("on_edited_message_unhandled", error=str(exc))

        new_handler = on_new_message
        edit_handler = on_edited_message

    await _reload()
    await register_handlers()

    while True:
        await asyncio.sleep(RELOAD_INTERVAL)
        try:
            await _reload()
        except Exception as exc:
            log.error("reload_channels_error", error=str(exc))
