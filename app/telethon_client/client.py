"""Telethon client setup and singleton."""
from __future__ import annotations

import asyncio
import os

import structlog
from telethon import TelegramClient
from telethon.errors import AuthKeyDuplicatedError
from telethon.sessions import StringSession

from app.config import settings

log = structlog.get_logger(__name__)

_session_string = os.environ.get("TELEGRAM_SESSION_STRING", "").strip()


def _make_client() -> TelegramClient:
    session = StringSession(_session_string) if _session_string else StringSession()
    return TelegramClient(
        session,
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )


telethon_client = _make_client()


async def start_client() -> TelegramClient:
    """Start and authenticate the Telethon client.

    Retries on AuthKeyDuplicatedError caused by Railway deploying new container
    before old one fully stops. Waits up to ~5 minutes total.
    """
    global telethon_client
    print(f"SESSION_STRING_LEN={len(_session_string)} STARTS={_session_string[:10] if _session_string else 'EMPTY'}", flush=True)

    for attempt in range(1, 15):
        try:
            if telethon_client.is_connected():
                await telethon_client.disconnect()
            telethon_client = _make_client()
            await telethon_client.connect()
            authorized = await telethon_client.is_user_authorized()
            print(f"IS_AUTHORIZED={authorized}", flush=True)
            if authorized:
                return telethon_client
            raise RuntimeError("Telethon not authorized. Set TELEGRAM_SESSION_STRING env var.")
        except AuthKeyDuplicatedError:
            wait = min(attempt * 15, 60)
            log.warning("auth_key_duplicated_retry", attempt=attempt, wait_seconds=wait)
            await asyncio.sleep(wait)

    raise RuntimeError("Could not connect Telethon: AuthKeyDuplicatedError after all retries.")
