"""Telethon event listeners for source channel monitoring."""
from __future__ import annotations

import asyncio
from typing import List, Set

import structlog
from telethon import TelegramClient, events

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services import sync_service

log = structlog.get_logger(__name__)

RELOAD_INTERVAL = 30  # seconds


async def _load_source_channel_ids() -> List[int]:
    """Fetch active source channel IDs from DB."""
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()
        return [s.telegram_id for s in sources]


async def run_listener(client: TelegramClient) -> None:
    """Start listening for messages and periodically reload channel list."""
    # Keep track of registered channel set to detect changes
    registered_ids: Set[int] = set()

    # Handlers registered with Telethon
    new_handler = None
    edit_handler = None

    async def register_handlers(channel_ids: List[int]) -> None:
        nonlocal new_handler, edit_handler, registered_ids

        if not channel_ids:
            log.info("no_source_channels_configured")
            return

        # Remove old handlers
        if new_handler is not None:
            client.remove_event_handler(new_handler)
        if edit_handler is not None:
            client.remove_event_handler(edit_handler)

        chats_arg = channel_ids if channel_ids else None

        @client.on(events.NewMessage(chats=chats_arg))
        async def on_new_message(event: events.NewMessage.Event) -> None:
            log.info("event_received", chat_id=event.chat_id, msg_id=event.message.id)
            try:
                await sync_service.handle_new_message(event, client)
            except Exception as exc:
                log.error("on_new_message_unhandled", error=str(exc))

        @client.on(events.MessageEdited(chats=chats_arg))
        async def on_edited_message(event: events.MessageEdited.Event) -> None:
            try:
                await sync_service.handle_edited_message(event, client)
            except Exception as exc:
                log.error("on_edited_message_unhandled", error=str(exc))

        new_handler = on_new_message
        edit_handler = on_edited_message
        registered_ids = set(channel_ids)
        log.info("handlers_registered", count=len(channel_ids))

    # Initial load
    ids = await _load_source_channel_ids()
    await register_handlers(ids)

    # Periodic reload loop
    while True:
        await asyncio.sleep(RELOAD_INTERVAL)
        try:
            new_ids = await _load_source_channel_ids()
            if set(new_ids) != registered_ids:
                log.info(
                    "reloading_channels",
                    old_count=len(registered_ids),
                    new_count=len(new_ids),
                )
                await register_handlers(new_ids)
        except Exception as exc:
            log.error("reload_channels_error", error=str(exc))
