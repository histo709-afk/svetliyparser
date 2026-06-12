"""Telethon client setup and singleton."""
from __future__ import annotations

import os

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import settings

_session_string = os.environ.get("TELEGRAM_SESSION_STRING", "")
_session = StringSession(_session_string) if _session_string else StringSession()

telethon_client = TelegramClient(
    _session,
    settings.TELEGRAM_API_ID,
    settings.TELEGRAM_API_HASH,
)


async def start_client() -> TelegramClient:
    """Start and authenticate the Telethon client."""
    if not telethon_client.is_connected():
        await telethon_client.start(phone=settings.TELEGRAM_PHONE)
    return telethon_client
