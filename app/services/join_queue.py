"""Background join queue: connect a large source base without tripping Telegram.

The inline Excel import joins every channel inside one handler call, one
second apart. That is fine for a city's dozen sources and hopeless for a
regional base of several hundred: Telegram starts answering joins with flood
waits after a few dozen, the import helper gives up after sleeping 60 seconds,
and the rest of the file is reported as errors. The queue instead joins one
channel every JOIN_QUEUE_INTERVAL seconds, sleeps out whatever flood wait it
is given in full, and keeps its place in the database across deploys.
"""
from __future__ import annotations

import asyncio
import csv
import os
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChannelsTooMuchError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    InviteRequestSentError,
    UserAlreadyParticipantError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import Channel, ChatInviteAlready

from app.database import async_session_factory
from app.models.join_queue import JoinQueueItem
from app.repositories.channel_repo import ChannelRepository
from app.services.channel_service import create_route, parse_channel_link

log = structlog.get_logger(__name__)

Notify = Callable[[str], Awaitable[None]]

# One join per this many seconds. Tunable from Railway without a code change.
JOIN_QUEUE_INTERVAL = int(os.environ.get("JOIN_QUEUE_INTERVAL", "180"))
# Let the boot-time cursor init and the first poll laps go first.
STARTUP_DELAY = 120
IDLE_SLEEP = 300
# Joining past the account's channel limit fails until a slot frees up or the
# limit is raised (Premium). Re-check this often rather than spinning.
TOO_MANY_CHANNELS_SLEEP = 6 * 3600
MAX_ATTEMPTS = 3

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Bases seeded into the queue on boot, as (batch, destination id, csv file).
# Inserting is idempotent per (link, destination), so a redeploy re-seeds
# nothing. Added here rather than via the bot because the base arrived as a
# file on the operator's machine, not through the bot's chat.
SEED_BATCHES: list[tuple[str, int, str]] = [
    ("ural", -1004455437967, "ural_sources.csv"),
]


async def enqueue(
    links: Iterable[tuple[str, Optional[str]]],
    dest_telegram_id: int,
    batch: Optional[str] = None,
) -> int:
    """Queue (link, title) pairs for joining. Returns how many were new."""
    rows = [
        {"link": link.strip(), "title": title, "dest_telegram_id": dest_telegram_id,
         "priority": i, "batch": batch}
        for i, (link, title) in enumerate(links)
        if link and link.strip()
    ]
    if not rows:
        return 0
    async with async_session_factory() as session:
        stmt = insert(JoinQueueItem).values(rows).on_conflict_do_nothing(
            index_elements=["link", "dest_telegram_id"]
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0


async def _seed() -> None:
    for batch, dest_id, filename in SEED_BATCHES:
        path = _DATA_DIR / filename
        if not path.exists():
            log.warning("join_queue_seed_missing", file=str(path))
            continue
        with path.open(encoding="utf-8") as fh:
            links = [(row["link"], row.get("title")) for row in csv.DictReader(fh)]
        added = await enqueue(links, dest_id, batch=batch)
        if added:
            log.info("join_queue_seeded", batch=batch, added=added)


async def queue_stats() -> dict:
    """Counts by status per batch, plus the latest failures."""
    async with async_session_factory() as session:
        counts = await session.execute(
            select(JoinQueueItem.batch, JoinQueueItem.status, func.count())
            .group_by(JoinQueueItem.batch, JoinQueueItem.status)
        )
        failed = await session.execute(
            select(JoinQueueItem)
            .where(JoinQueueItem.status == "failed")
            .order_by(JoinQueueItem.updated_at.desc())
            .limit(10)
        )
        by_batch: dict[str, dict[str, int]] = {}
        for batch, status, n in counts.all():
            by_batch.setdefault(batch or "—", {})[status] = n
        return {"batches": by_batch, "failed": list(failed.scalars().all())}


async def _ensure_destination(bot, dest_telegram_id: int) -> int:
    """Return the destination's row id, registering it on first use.

    The title comes from the Bot API: the bot is the one posting there, so it
    is an admin, whereas the userbot usually isn't even a member.
    """
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dest = await repo.get_destination_by_telegram_id(dest_telegram_id)
        if dest is None:
            title, username = None, None
            try:
                chat = await bot.get_chat(dest_telegram_id)
                title, username = chat.title, chat.username
            except Exception as exc:
                log.warning("join_queue_dest_lookup_failed", dest=dest_telegram_id, error=str(exc)[:120])
            dest = await repo.add_destination(
                telegram_id=dest_telegram_id, username=username, title=title or str(dest_telegram_id),
            )
            await session.commit()
        elif not dest.is_active:
            dest.is_active = True
            await session.commit()
        return dest.id


class _Skip(Exception):
    """This item can't be joined, and retrying won't change that."""


async def _join(client: TelegramClient, link: str) -> Channel:
    identifier = parse_channel_link(link)
    if not identifier:
        raise _Skip("пустая ссылка")

    if identifier.startswith("+"):
        invite_hash = identifier[1:]
        try:
            result = await client(ImportChatInviteRequest(invite_hash))
            chats = result.chats
        except UserAlreadyParticipantError:
            info = await client(CheckChatInviteRequest(invite_hash))
            if not isinstance(info, ChatInviteAlready):
                raise _Skip("уже участник, но канал не виден")
            chats = [info.chat]
        except (InviteHashExpiredError, InviteHashInvalidError):
            raise _Skip("ссылка-приглашение недействительна")
    else:
        try:
            result = await client(JoinChannelRequest(identifier))
        except (UsernameNotOccupiedError, UsernameInvalidError):
            raise _Skip("юзернейм не существует")
        except ValueError as exc:
            # Telethon's own "No user has X as username" on resolve.
            raise _Skip(f"не найден: {str(exc)[:60]}")
        chats = result.chats

    channel = next((c for c in chats if isinstance(c, Channel)), None)
    if channel is None:
        raise _Skip("не канал")
    return channel


async def _process(client: TelegramClient, bot, item: JoinQueueItem) -> None:
    channel = await _join(client, item.link)

    if channel.megagroup:
        # A group posts every member's message — nothing to forward from.
        try:
            await client(LeaveChannelRequest(channel))
        except Exception:
            pass
        raise _Skip("это чат, а не канал")

    dest_id = await _ensure_destination(bot, item.dest_telegram_id)
    telegram_id = int(f"-100{channel.id}")
    normalized = parse_channel_link(item.link)
    invite_link = (
        f"https://t.me/{normalized}"
        if not channel.username and normalized.startswith("+") else None
    )

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        src = await repo.get_source_by_telegram_id(telegram_id)
        if src is None:
            src = await repo.add_source(
                telegram_id=telegram_id,
                username=channel.username,
                title=channel.title,
                invite_link=invite_link,
            )
        else:
            src.is_active = True
            if invite_link and not src.invite_link:
                src.invite_link = invite_link
        await create_route(session, src.id, dest_id)
        await session.commit()


async def _next_pending() -> Optional[JoinQueueItem]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(JoinQueueItem)
            .where(JoinQueueItem.status == "pending")
            .order_by(JoinQueueItem.priority, JoinQueueItem.id)
            .limit(1)
        )
        return result.scalars().first()


async def _update(item_id: int, **fields) -> None:
    async with async_session_factory() as session:
        item = await session.get(JoinQueueItem, item_id)
        if item is None:
            return
        for key, value in fields.items():
            setattr(item, key, value)
        await session.commit()


async def _report_done(notify: Notify, batch: Optional[str]) -> None:
    stats = await queue_stats()
    counts = stats["batches"].get(batch or "—", {})
    await notify(
        f"✅ <b>Очередь вступлений «{batch or '—'}» пройдена.</b>\n\n"
        f"Подключено: <b>{counts.get('done', 0)}</b>\n"
        f"Не удалось: <b>{counts.get('failed', 0)}</b>\n\n"
        f"Подробности — /joinqueue"
    )


async def run_join_queue(client: TelegramClient, bot, notify: Notify) -> None:
    """Work the queue forever. Never raises: it shares a gather with the
    listener and the poller, and must not take them down with it."""
    try:
        await _seed()
    except Exception as exc:
        log.error("join_queue_seed_failed", error=str(exc)[:200])

    await asyncio.sleep(STARTUP_DELAY)
    log.info("join_queue_started", interval=JOIN_QUEUE_INTERVAL)
    warned_too_many = False
    last_batch: Optional[str] = None

    while True:
        try:
            item = await _next_pending()
            if item is None:
                if last_batch is not None:
                    await _report_done(notify, last_batch)
                    last_batch = None
                await asyncio.sleep(IDLE_SLEEP)
                continue
            last_batch = item.batch

            try:
                await _process(client, bot, item)
            except FloodWaitError as exc:
                # Not the item's fault — wait it out in full and retry it.
                log.warning("join_queue_flood_wait", seconds=exc.seconds, link=item.link)
                await asyncio.sleep(exc.seconds + 5)
                continue
            except ChannelsTooMuchError:
                log.error("join_queue_channels_too_much", link=item.link)
                if not warned_too_many:
                    await notify(
                        "⚠️ <b>Юзербот упёрся в лимит каналов.</b>\n\n"
                        "Telegram не даёт вступить больше (500 без Premium, 1000 с Premium). "
                        "Очередь на паузе и будет пробовать снова раз в 6 часов. "
                        "Статус — /joinqueue"
                    )
                    warned_too_many = True
                await asyncio.sleep(TOO_MANY_CHANNELS_SLEEP)
                continue
            except InviteRequestSentError:
                await _update(item.id, status="failed", error="канал по заявкам — заявка отправлена")
            except ChannelPrivateError:
                await _update(item.id, status="failed", error="канал закрыт или нас забанили")
            except _Skip as exc:
                await _update(item.id, status="failed", error=str(exc)[:255])
            except Exception as exc:
                attempts = item.attempts + 1
                log.warning("join_queue_item_error", link=item.link, attempt=attempts, error=str(exc)[:160])
                await _update(
                    item.id,
                    attempts=attempts,
                    status="failed" if attempts >= MAX_ATTEMPTS else "pending",
                    error=f"[{type(exc).__name__}] {str(exc)[:200]}",
                )
            else:
                warned_too_many = False
                await _update(item.id, status="done", error=None)
                log.info("join_queue_joined", link=item.link)

            await asyncio.sleep(JOIN_QUEUE_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("join_queue_loop_error", error=str(exc)[:200])
            await asyncio.sleep(60)
