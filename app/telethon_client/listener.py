"""Telethon event listeners for source channel monitoring."""
from __future__ import annotations

import asyncio
from typing import Dict, Set

import structlog
from telethon import TelegramClient, events

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services import sync_service

log = structlog.get_logger(__name__)

RELOAD_INTERVAL = 30  # seconds


async def _load_sources() -> Dict[int, str]:
    """Fetch active sources: {telegram_id: username}."""
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()
        return {s.telegram_id: (s.username or "") for s in sources}



async def run_listener(client: TelegramClient) -> None:
    """Start listening for messages and periodically reload channel list."""
    registered_ids: Set[int] = set()
    new_handler = None
    edit_handler = None

    async def register_handlers(ids_set: Set[int]) -> None:
        nonlocal new_handler, edit_handler, registered_ids

        if new_handler is not None:
            client.remove_event_handler(new_handler)
        if edit_handler is not None:
            client.remove_event_handler(edit_handler)

        @client.on(events.NewMessage())
        async def on_new_message(event: events.NewMessage.Event) -> None:
            if event.chat_id not in ids_set:
                return
            log.info("event_received", chat_id=event.chat_id, msg_id=event.message.id)
            try:
                await sync_service.handle_new_message(event, client)
            except Exception as exc:
                log.error("on_new_message_unhandled", error=str(exc))

        @client.on(events.MessageEdited())
        async def on_edited_message(event: events.MessageEdited.Event) -> None:
            if event.chat_id not in ids_set:
                return
            try:
                await sync_service.handle_edited_message(event, client)
            except Exception as exc:
                log.error("on_edited_message_unhandled", error=str(exc))

        raw_handler = None
        new_handler = on_new_message
        edit_handler = on_edited_message
        registered_ids = ids_set
        log.info("handlers_registered", count=len(ids_set))

    sources = await _load_sources()
    await register_handlers(set(sources.keys()))

    while True:
        await asyncio.sleep(RELOAD_INTERVAL)
        try:
            new_sources = await _load_sources()
            new_ids = set(new_sources.keys())
            if new_ids != registered_ids:
                log.info("reloading_channels", old=len(registered_ids), new=len(new_ids))
                await register_handlers(new_ids)
        except Exception as exc:
            log.error("reload_channels_error", error=str(exc))
