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

    # Show list grouped by type
    lines = [f"✅ Найдено {len(channels)} каналов/групп:\n"]
    for cid, title in sorted(channels, key=lambda x: x[1]):
        lines.append(f"• {title}: `{cid}`")

    # Split into chunks of 50
    chunk = []
    for line in lines:
        chunk.append(line)
        if len(chunk) >= 50:
            await message.answer("\n".join(chunk), parse_mode="Markdown")
            chunk = []
    if chunk:
        await message.answer("\n".join(chunk), parse_mode="Markdown")
