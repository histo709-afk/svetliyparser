"""Business logic for managing channels and routes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import UsernameInvalidError, UsernameNotOccupiedError, FloodWaitError
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import Channel, Chat, ChatInviteAlready, ChatInvite

from app.models.channel import DestinationChannel, SourceChannel
from app.models.route import Route
from app.repositories.channel_repo import ChannelRepository
from app.repositories.route_repo import RouteRepository

log = structlog.get_logger(__name__)


@dataclass
class ChannelInfo:
    telegram_id: int
    username: Optional[str]
    title: str


def parse_channel_link(text: str) -> str:
    """Extract username/identifier from various link formats.

    Accepts:
    - https://t.me/channel
    - t.me/channel
    - @channel
    - channel
    Returns the identifier without @ or URL prefix.
    """
    text = text.strip()
    # Strip URL
    text = re.sub(r"https?://t\.me/", "", text)
    text = re.sub(r"t\.me/", "", text)
    # Strip leading @
    text = text.lstrip("@")
    # Remove trailing slashes
    text = text.rstrip("/")
    return text


async def resolve_channel(
    client: TelegramClient, link: str
) -> Optional[ChannelInfo]:
    """Resolve a channel link to ChannelInfo using Telethon."""
    identifier = parse_channel_link(link)
    if not identifier:
        return None

    # Handle private invite links (hash starts with +)
    if identifier.startswith("+"):
        invite_hash = identifier[1:]

        # Check Redis cache first to avoid repeated CheckChatInviteRequest calls
        try:
            import redis.asyncio as aioredis
            from app.config import settings as _s
            _r = aioredis.from_url(_s.REDIS_URL, decode_responses=True)
            cached = await _r.get(f"invite_cache:{invite_hash}")
            if not cached:
                # Also check dialog_id cache from /sync_dialogs command
                cached = await _r.get(f"invite_hash_to_id:{invite_hash}")
            await _r.aclose()
            if cached:
                telegram_id = int(cached)
                return ChannelInfo(telegram_id=telegram_id, username=None, title=invite_hash)
        except Exception:
            pass

        try:
            result = await client(CheckChatInviteRequest(invite_hash))
            if isinstance(result, ChatInviteAlready):
                entity = result.chat
            else:
                log.warning("resolve_invite_not_joined", hash=invite_hash)
                return None
        except FloodWaitError as e:
            log.warning("resolve_invite_flood_wait", hash=invite_hash, seconds=e.seconds)
            await asyncio.sleep(e.seconds + 1)
            try:
                result = await client(CheckChatInviteRequest(invite_hash))
                if isinstance(result, ChatInviteAlready):
                    entity = result.chat
                else:
                    return None
            except Exception as exc2:
                log.warning("resolve_invite_failed_retry", hash=invite_hash, error=str(exc2))
                raise ValueError(f"[retry][{type(exc2).__name__}] {exc2}") from exc2
        except Exception as exc:
            log.warning("resolve_invite_failed", hash=invite_hash, error=str(exc))
            raise ValueError(f"[{type(exc).__name__}] {exc}") from exc
    else:
        try:
            entity = await client.get_entity(identifier)
        except (UsernameInvalidError, UsernameNotOccupiedError, ValueError) as exc:
            log.warning("resolve_channel_failed", identifier=identifier, error=str(exc))
            return None
        except Exception as exc:
            log.error("resolve_channel_error", identifier=identifier, error=str(exc))
            return None

    if not isinstance(entity, (Channel, Chat)):
        log.warning("not_a_channel", identifier=identifier, type=type(entity).__name__)
        return None

    raw_id: int = entity.id
    telegram_id = int(f"-100{raw_id}")

    # Cache invite hash → telegram_id in Redis
    if identifier.startswith("+"):
        try:
            import redis.asyncio as aioredis
            from app.config import settings as _s
            _r = aioredis.from_url(_s.REDIS_URL, decode_responses=True)
            await _r.set(f"invite_cache:{identifier[1:]}", str(telegram_id), ex=604800)
            await _r.aclose()
        except Exception:
            pass

    username: Optional[str] = getattr(entity, "username", None)
    title: str = getattr(entity, "title", identifier)

    return ChannelInfo(telegram_id=telegram_id, username=username, title=title)


async def add_source_channel(
    session: AsyncSession,
    client: TelegramClient,
    link: str,
) -> tuple[SourceChannel, bool]:
    """Add or retrieve a source channel. Returns (channel, created)."""
    info = await resolve_channel(client, link)
    if info is None:
        raise ValueError(f"Не удалось найти канал по ссылке: {link}")

    repo = ChannelRepository(session)
    existing = await repo.get_source_by_telegram_id(info.telegram_id)
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await session.flush()
        return existing, False

    channel = await repo.add_source(
        telegram_id=info.telegram_id,
        username=info.username,
        title=info.title,
    )
    return channel, True


async def add_destination_channel(
    session: AsyncSession,
    client: TelegramClient,
    link: str,
) -> tuple[DestinationChannel, bool]:
    """Add or retrieve a destination channel. Returns (channel, created)."""
    info = await resolve_channel(client, link)
    if info is None:
        raise ValueError(f"Не удалось найти канал по ссылке: {link}")

    repo = ChannelRepository(session)
    existing = await repo.get_destination_by_telegram_id(info.telegram_id)
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await session.flush()
        return existing, False

    channel = await repo.add_destination(
        telegram_id=info.telegram_id,
        username=info.username,
        title=info.title,
    )
    return channel, True


async def create_route(
    session: AsyncSession,
    source_id: int,
    destination_id: int,
) -> tuple[Route, bool]:
    """Create a route between source and destination. Returns (route, created)."""
    repo = RouteRepository(session)
    existing = await repo.get_route(source_id, destination_id)
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await session.flush()
        return existing, False
    route = await repo.add_route(source_id, destination_id)
    return route, True


def channel_display_name(ch: SourceChannel | DestinationChannel) -> str:
    if ch.username:
        return f"@{ch.username} ({ch.title or 'без названия'})"
    return ch.title or f"ID: {ch.telegram_id}"
