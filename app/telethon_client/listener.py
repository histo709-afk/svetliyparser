"""Telethon event listeners for source channel monitoring."""
from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from telethon import TelegramClient, events
from telethon.tl.types import UpdateNewChannelMessage, UpdateEditChannelMessage

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services import sync_service

log = structlog.get_logger(__name__)

RELOAD_INTERVAL = 60  # seconds


async def _try_fix_channel_id(client: TelegramClient, chat_id: int, peer=None) -> bool:
    """
    When an event arrives from an unknown chat_id, try to resolve it via Telethon
    and match to a source by username. Updates telegram_id in DB if found.
    Returns True if the channel was found and fixed.
    """
    try:
        entity = await client.get_entity(peer if peer is not None else chat_id)
    except Exception as e:
        log.warning("fix_channel_get_entity_failed", chat_id=chat_id, error=str(e))
        return False

    username = getattr(entity, "username", None)
    if not username:
        return False

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()
        for src in sources:
            if (src.username or "").lower() == username.lower() and src.telegram_id != chat_id:
                log.info("auto_fix_telegram_id", username=username, old=src.telegram_id, new=chat_id)
                src.telegram_id = chat_id
                await session.commit()
                return True
    return False


async def run_listener(client: TelegramClient) -> None:
    """Start listening for messages and periodically reload channel list."""

    # usernames_set: lowercase usernames of active sources (for fast lookup)
    known_ids: set[int] = set()
    new_handler = None
    edit_handler = None

    async def _reload() -> None:
        nonlocal known_ids
        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            sources = await repo.list_active_sources()
            known_ids = {s.telegram_id for s in sources}
        log.info("sources_loaded", count=len(known_ids))

    async def register_handlers() -> None:
        nonlocal new_handler, edit_handler

        if new_handler is not None:
            client.remove_event_handler(new_handler)
        if edit_handler is not None:
            client.remove_event_handler(edit_handler)

        @client.on(events.Raw(UpdateNewChannelMessage))
        async def on_raw_channel(update) -> None:
            cid = getattr(getattr(update.message, "peer_id", None), "channel_id", None)
            log.info("raw_channel_update", channel_id=cid, msg_id=getattr(update.message, "id", None))

        @client.on(events.NewMessage())
        async def on_new_message(event: events.NewMessage.Event) -> None:
            chat_id = event.chat_id
            if chat_id not in known_ids:
                log.info("unknown_channel_event", chat_id=chat_id, msg_id=event.message.id)
                peer = getattr(event.message, "peer_id", None)
                fixed = await _try_fix_channel_id(client, chat_id, peer=peer)
                if fixed:
                    await _reload()
                    # Process the message now that ID is fixed
                else:
                    log.info("unknown_channel_skipped", chat_id=chat_id)
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
        # raw_channel_handler intentionally not tracked — diagnostic only

    await _reload()
    await register_handlers()

    while True:
        await asyncio.sleep(RELOAD_INTERVAL)
        try:
            old_count = len(known_ids)
            await _reload()
            if len(known_ids) != old_count:
                log.info("channels_updated", count=len(known_ids))
        except Exception as exc:
            log.error("reload_channels_error", error=str(exc))
