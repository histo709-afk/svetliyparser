"""Telethon client setup and singleton."""
from __future__ import annotations

import os

from telethon import TelegramClient

from app.config import settings

# Session file stored in sessions/ directory (Docker volume)
_session_path = os.path.join("sessions", settings.SESSION_NAME)

telethon_client = TelegramClient(
    _session_path,
    settings.TELEGRAM_API_ID,
    settings.TELEGRAM_API_HASH,
)


async def start_client() -> TelegramClient:
    """Start and authenticate the Telethon client."""
    if not telethon_client.is_connected():
        await telethon_client.start(phone=settings.TELEGRAM_PHONE)
    return telethon_client
