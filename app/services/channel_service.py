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
    - https://t.me/+HASH or t.me/joinchat/HASH (private invite, old and new style)
    - @channel
    - channel
    Returns the identifier without @ or URL prefix. Private invite links are
    normalized to the modern "+HASH" form regardless of which style was given.
    """
    text = text.strip()
    # Strip URL
    text = re.sub(r"https?://t\.me/", "", text)
    text = re.sub(r"t\.me/", "", text)
    # Normalize legacy invite links: joinchat/HASH -> +HASH
    text = re.sub(r"^joinchat/", "+", text)
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

    # Handle numeric IDs
    if identifier.lstrip("-").isdigit():
        try:
            entity = await client.get_entity(int(identifier))
        except Exception as exc:
            log.warning("resolve_channel_failed", identifier=identifier, error=str(exc))
            return None
        if not isinstance(entity, (Channel, Chat)):
            return None
        raw_id = entity.id
        telegram_id = int(f"-100{raw_id}") if raw_id > 0 else raw_id
        return ChannelInfo(
            telegram_id=telegram_id,
            username=getattr(entity, "username", None),
            title=getattr(entity, "title", identifier),
        )

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

    # Persist the invite link only when there's no username to fall back on —
    # that's the only case where losing it would make the channel
    # unrejoinable later (e.g. after the account gets removed).
    normalized = parse_channel_link(link)
    invite_link = f"https://t.me/{normalized}" if not info.username and normalized.startswith("+") else None

    repo = ChannelRepository(session)
    existing = await repo.get_source_by_telegram_id(info.telegram_id)
    if existing is not None:
        if not existing.is_active:
            existing.is_active = True
            await session.flush()
        if invite_link and not existing.invite_link:
            existing.invite_link = invite_link
            await session.flush()
        return existing, False

    channel = await repo.add_source(
        telegram_id=info.telegram_id,
        username=info.username,
        title=info.title,
        invite_link=invite_link,
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


async def join_channel_link(client: TelegramClient, link: str) -> bool:
    """Make the userbot account join a channel (public @username or private +invite).
    Returns True if joined or already a member, False on failure.
    Safe to call repeatedly — already-member is treated as success."""
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.tl.functions.messages import ImportChatInviteRequest
    from telethon.errors import (
        UserAlreadyParticipantError,
        InviteHashExpiredError,
        InviteHashInvalidError,
        FloodWaitError,
    )

    identifier = parse_channel_link(link)
    if not identifier:
        return False

    # Private invite link (+hash)
    if identifier.startswith("+"):
        invite_hash = identifier[1:]
        try:
            await client(ImportChatInviteRequest(invite_hash))
            return True
        except UserAlreadyParticipantError:
            return True
        except FloodWaitError as e:
            log.warning("join_flood_wait", link=link, seconds=e.seconds)
            await asyncio.sleep(min(e.seconds, 60))
            try:
                await client(ImportChatInviteRequest(invite_hash))
                return True
            except UserAlreadyParticipantError:
                return True
            except Exception as exc:
                log.warning("join_invite_failed_retry", hash=invite_hash, error=str(exc)[:80])
                return False
        except (InviteHashExpiredError, InviteHashInvalidError) as exc:
            log.warning("join_invite_bad_hash", hash=invite_hash, error=str(exc)[:80])
            return False
        except Exception as exc:
            log.warning("join_invite_failed", hash=invite_hash, error=str(exc)[:80])
            return False

    # Public channel (@username)
    try:
        await client(JoinChannelRequest(identifier))
        return True
    except UserAlreadyParticipantError:
        return True
    except FloodWaitError as e:
        log.warning("join_flood_wait", link=link, seconds=e.seconds)
        await asyncio.sleep(min(e.seconds, 60))
        try:
            await client(JoinChannelRequest(identifier))
            return True
        except UserAlreadyParticipantError:
            return True
        except Exception as exc:
            log.warning("join_public_failed_retry", identifier=identifier, error=str(exc)[:80])
            return False
    except Exception as exc:
        log.warning("join_public_failed", identifier=identifier, error=str(exc)[:80])
        return False


def channel_display_name(ch: SourceChannel | DestinationChannel) -> str:
    if ch.username:
        return f"@{ch.username} ({ch.title or 'без названия'})"
    return ch.title or f"ID: {ch.telegram_id}"
