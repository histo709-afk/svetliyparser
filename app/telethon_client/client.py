"""Telethon client setup and singleton."""
from __future__ import annotations

import os

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import settings

_session_string = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()
_session = StringSession(_session_string) if _session_string else StringSession()

telethon_client = TelegramClient(
    _session,
    settings.TELEGRAM_API_ID,
    settings.TELEGRAM_API_HASH,
)


async def start_client() -> TelegramClient:
    """Start and authenticate the Telethon client."""
    print(f"SESSION_STRING_LEN={len(_session_string)} STARTS={_session_string[:10] if _session_string else 'EMPTY'}", flush=True)
    await telethon_client.connect()
    authorized = await telethon_client.is_user_authorized()
    print(f"IS_AUTHORIZED={authorized}", flush=True)
    if authorized:
        return telethon_client
    raise RuntimeError("Telethon not authorized. Set TELEGRAM_SESSION_STRING env var.")
