"""Handler to refresh telegram_ids for all source channels via Bot API."""
from __future__ import annotations

import asyncio

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

router = Router(name="refresh_sources")


@router.message(Command("fixids"))
async def fix_ids(message: Message) -> None:
    """Refresh telegram_ids using Bot API get_chat (no Telethon flood limit)."""
    from app.config import settings
    bot = Bot(token=settings.BOT_TOKEN)

    await message.answer("🔄 Обновляю ID каналов через Bot API...")

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()

    updated = 0
    skipped = 0
    errors = []

    for src in sources:
        if not src.username:
            skipped += 1
            continue
        try:
            chat = await bot.get_chat(f"@{src.username}")
            new_id = chat.id
            if new_id != src.telegram_id:
                async with async_session_factory() as session:
                    repo = ChannelRepository(session)
                    ch = await repo.get_source_by_id(src.id)
                    if ch:
                        ch.telegram_id = new_id
                        await session.commit()
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"@{src.username}: {str(e)[:50]}")
        await asyncio.sleep(0.1)

    await bot.session.close()

    text = (
        f"✅ <b>Готово!</b>\n\n"
        f"• Обновлено ID: <b>{updated}</b>\n"
        f"• Без изменений: <b>{skipped}</b>\n"
    )
    if errors:
        text += f"\n⚠️ Ошибки ({len(errors)}):\n" + "\n".join(errors[:15])

    await message.answer(text, parse_mode="HTML")


@router.message(Command("refreshsources"))
async def refresh_sources(message: Message) -> None:
    await message.answer("Используй /fixids — быстрее и без флуд-лимитов.")
