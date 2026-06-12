"""Handler to sync channel IDs from Telethon dialogs into DB."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

router = Router(name="sync_dialogs")


@router.message(Command("sync_dialogs"))
async def sync_dialogs(message: Message) -> None:
    """Iterate all Telethon dialogs and cache channel IDs into Redis."""
    from app.telethon_client.client import telethon_client

    await message.answer("🔄 Получаю список каналов из аккаунта...")

    channels = []
    async for dialog in telethon_client.iter_dialogs():
        if dialog.is_channel or dialog.is_group:
            cid = dialog.id
            # Normalize to -100... format
            if cid > 0:
                cid = int(f"-100{cid}")
            channels.append((cid, dialog.name or ""))

    # Store all in Redis cache (title → id and id → title)
    try:
        import redis.asyncio as aioredis
        from app.config import settings
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        for cid, title in channels:
            await r.set(f"dialog_title:{title.lower()}", str(cid), ex=86400)
            await r.set(f"dialog_id:{cid}", title, ex=86400)
        await r.aclose()
    except Exception as e:
        await message.answer(f"⚠️ Redis ошибка: {e}")
        return

    # Show only "Парсер" channels
    parser_channels = [(cid, title) for cid, title in channels if "парсер" in title.lower()]
    lines = [f"✅ Каналы 'Парсер' ({len(parser_channels)} шт):\n"]
    for cid, title in sorted(parser_channels, key=lambda x: x[1]):
        lines.append(f"• {title}: `{cid}`")

    if not parser_channels:
        lines.append("(не найдено — попробуй /sync_dialogs_all для полного списка)")

    await message.answer("\n".join(lines), parse_mode="Markdown")
