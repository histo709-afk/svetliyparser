"""Auto-discover and add public source channels for a city via Telegram's
own contacts.search (Telethon) — no web scraping, no external service.

Private (username-less) channels are invisible to this search by design
(Telegram's global search only surfaces resolvable public entities), so
they stay a manual step via /setinvitelink, same as before this command
existed. That's a hard platform limitation, not a gap in this code.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.types import Channel

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services.channel_service import add_source_channel, create_route, join_channel_link

router = Router(name="collect_sources")
log = structlog.get_logger(__name__)

QUERY_SUFFIXES = ["новости", "новости сегодня", "СМИ", ""]
RELEVANCE_KEYWORDS = ["новост", "сми", "происшеств", "событ", "инцидент"]
POSTS_FOR_ENGAGEMENT = 20
MAX_DAYS_SINCE_LAST_POST = 14
MIN_SUBSCRIBERS = 500
DEFAULT_TOP_N = 50
# Hard cap on how many candidates get the full enrich pass (subscriber count,
# recent posts) in one run — each candidate costs a few API calls plus a
# throttling sleep, so an unbounded list on a big city could run for a very
# long time and risk flood limits.
MAX_CANDIDATES_TO_ENRICH = 80


@dataclass
class ChannelCandidate:
    username: str
    title: str
    subscribers: int = 0
    about: str = ""
    avg_views: float = 0.0
    engagement_rate: float = 0.0
    score: float = 0.0


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


def _is_relevant(title: str, about: str) -> bool:
    text = f"{title} {about}".lower()
    return any(kw in text for kw in RELEVANCE_KEYWORDS)


async def _search_candidates(client, city: str) -> dict[str, ChannelCandidate]:
    """Fan out across a few query phrasings and merge unique public channels.
    Only entities with a username come back from global search at all —
    private channels are never in this result set."""
    found: dict[str, ChannelCandidate] = {}
    for suffix in QUERY_SUFFIXES:
        query = f"{city} {suffix}".strip()
        try:
            result = await client(SearchRequest(q=query, limit=50))
        except Exception as exc:
            log.warning("collectsources_search_failed", query=query, error=str(exc)[:120])
            await asyncio.sleep(1.5)
            continue
        for chat in result.chats:
            if not isinstance(chat, Channel) or chat.megagroup:
                continue
            username = getattr(chat, "username", None)
            if not username or username in found:
                continue
            found[username] = ChannelCandidate(username=username, title=chat.title or "")
        await asyncio.sleep(1.5)
    return found


async def _enrich_candidate(client, cand: ChannelCandidate) -> Optional[ChannelCandidate]:
    """Fetch subscriber count + recent-post engagement; returns None if the
    channel fails any filter (too small, off-topic, or gone quiet)."""
    try:
        entity = await client.get_entity(cand.username)
        full = await client(GetFullChannelRequest(channel=entity))
    except Exception as exc:
        log.warning("collectsources_enrich_failed", username=cand.username, error=str(exc)[:120])
        return None

    cand.subscribers = full.full_chat.participants_count or 0
    cand.about = full.full_chat.about or ""

    if cand.subscribers < MIN_SUBSCRIBERS or not _is_relevant(cand.title, cand.about):
        return None

    views = []
    last_date = None
    try:
        async for msg in client.iter_messages(entity, limit=POSTS_FOR_ENGAGEMENT):
            if last_date is None:
                last_date = msg.date
            if msg.views:
                views.append(msg.views)
    except Exception as exc:
        log.warning("collectsources_iter_messages_failed", username=cand.username, error=str(exc)[:120])
        return None

    if last_date is None or (datetime.now(timezone.utc) - last_date).days > MAX_DAYS_SINCE_LAST_POST:
        return None

    if views:
        cand.avg_views = sum(views) / len(views)
        cand.engagement_rate = round(cand.avg_views / cand.subscribers * 100, 2)

    cand.score = cand.avg_views * (1 + cand.engagement_rate / 100)
    return cand


@router.message(Command("collectsources"))
async def cmd_collect_sources(message: Message) -> None:
    """Find, join, and wire up public source channels for a city automatically.
    Usage: /collectsources <Город> [топ_N]
    Requires a destination "Парсер <Город>" already created via /newcity."""
    parts = message.text.split(maxsplit=2) if message.text else []
    if len(parts) < 2:
        await message.answer(
            "Использование: <code>/collectsources Город [топ_N]</code>\n\n"
            "Сначала создай канал назначения через <code>/newcity Город</code>.",
            parse_mode="HTML",
        )
        return

    city = parts[1].strip()
    try:
        top_n = int(parts[2]) if len(parts) > 2 else DEFAULT_TOP_N
    except ValueError:
        top_n = DEFAULT_TOP_N

    title = f"Парсер {city}"

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dest = next(
            (d for d in await repo.list_all_destinations() if d.title == title),
            None,
        )
    if dest is None:
        await message.answer(
            f"❌ Канал «{title}» не найден. Сначала выполни <code>/newcity {city}</code>.",
            parse_mode="HTML",
        )
        return

    client = _get_telethon_client()

    await message.answer(f"🔍 Ищу каналы для «{city}» через Telegram-поиск (это не веб-скрапинг)...")

    candidates = await _search_candidates(client, city)
    if not candidates:
        await message.answer("Каналы не найдены — попробуй другое название города.")
        return

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        existing_usernames = {(s.username or "").lower() for s in await repo.list_all_sources()}

    to_check = [c for c in candidates.values() if c.username.lower() not in existing_usernames]
    already_added = len(candidates) - len(to_check)
    truncated = len(to_check) > MAX_CANDIDATES_TO_ENRICH
    to_check = to_check[:MAX_CANDIDATES_TO_ENRICH]

    status = (
        f"📊 Найдено {len(candidates)} каналов ({already_added} уже в базе). "
        f"Проверяю {len(to_check)} новых — подписчики, активность, тематика..."
    )
    if truncated:
        status += f"\n(ограничил проверку {MAX_CANDIDATES_TO_ENRICH} каналами за раз, чтобы не словить лимиты Telegram)"
    await message.answer(status)

    enriched: list[ChannelCandidate] = []
    for cand in to_check:
        result = await _enrich_candidate(client, cand)
        if result:
            enriched.append(result)
        await asyncio.sleep(1.0)

    if not enriched:
        await message.answer(
            f"⚠️ Ни один канал не прошёл фильтры (мин. {MIN_SUBSCRIBERS} подписчиков, "
            f"пост не старше {MAX_DAYS_SINCE_LAST_POST} дней, тематика новости/СМИ). "
            f"Попробуй другое написание города или добавляй каналы вручную."
        )
        return

    enriched.sort(key=lambda c: c.score, reverse=True)
    top = enriched[:top_n]

    await message.answer(
        f"✅ Отобрано <b>{len(top)}</b> из {len(enriched)} подходящих каналов. "
        f"Вступаю и строю маршруты в «{title}»...",
        parse_mode="HTML",
    )

    added = 0
    errors: list[str] = []
    for cand in top:
        try:
            ok = await join_channel_link(client, f"@{cand.username}")
            if not ok:
                errors.append(f"@{cand.username} — не удалось вступить (возможно flood wait)")
                await asyncio.sleep(1.0)
                continue
            async with async_session_factory() as session:
                src, _ = await add_source_channel(session, client, f"@{cand.username}")
                _, created = await create_route(session, src.id, dest.id)
                await session.commit()
            if created:
                added += 1
        except Exception as exc:
            errors.append(f"@{cand.username} — {str(exc)[:60]}")
        await asyncio.sleep(1.0)

    text = f"🏁 <b>Готово для «{city}»</b>\n\n• Добавлено маршрутов: <b>{added}</b>\n"
    if errors:
        text += f"• Ошибок: <b>{len(errors)}</b>\n" + "\n".join(errors[:15])
        if len(errors) > 15:
            text += f"\n...и ещё {len(errors) - 15}"
    text += (
        "\n\n⚠️ Приватные каналы (без username) этим поиском принципиально не находятся — "
        "Telegram не отдаёт их в результатах поиска для не-участников. Добавляй их вручную "
        "(инвайт-ссылка → <code>/setinvitelink</code>), как раньше."
    )
    await message.answer(text, parse_mode="HTML")
