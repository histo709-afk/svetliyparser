"""Handler to refresh telegram_ids for all source channels."""
from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

router = Router(name="refresh_sources")


@router.message(Command("refreshsources"))
async def refresh_sources(message: Message) -> None:
    from app.telethon_client.client import telethon_client

    await message.answer("🔄 Обновляю telegram_id источников...")

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
            entity = await telethon_client.get_entity(src.username)
            new_id = -int(f"100{entity.id}")
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
            errors.append(f"@{src.username}: {str(e)[:40]}")
        await asyncio.sleep(0.5)

    text = (
        f"✅ <b>Обновление завершено!</b>\n\n"
        f"• Обновлено ID: <b>{updated}</b>\n"
        f"• Без изменений: <b>{skipped}</b>\n"
    )
    if errors:
        text += f"\n⚠️ Ошибки ({len(errors)}):\n" + "\n".join(errors[:15])

    await message.answer(text, parse_mode="HTML")
