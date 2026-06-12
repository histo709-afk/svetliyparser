"""Handler to join all source channels with the Telethon userbot account."""
from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

router = Router(name="join_channels")


@router.message(Command("join_all"))
async def join_all_sources(message: Message) -> None:
    from app.telethon_client.client import telethon_client

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()

    if not sources:
        await message.answer("📭 Источники не найдены.")
        return

    await message.answer(f"⏳ Вступаю в {len(sources)} каналов-источников...")

    joined = 0
    already = 0
    errors = []

    for src in sources:
        try:
            # Try to get entity and join if not already member
            entity = await telethon_client.get_entity(src.telegram_id)
            try:
                await telethon_client(
                    __import__('telethon.tl.functions.channels', fromlist=['JoinChannelRequest']).JoinChannelRequest(entity)
                )
                joined += 1
            except Exception as e:
                err_str = str(e)
                if "already" in err_str.lower() or "UserAlreadyParticipant" in err_str:
                    already += 1
                else:
                    errors.append(f"{src.username or src.telegram_id}: {err_str[:40]}")
        except Exception as e:
            errors.append(f"{src.username or src.telegram_id}: {str(e)[:40]}")

        await asyncio.sleep(1)  # avoid flood

    text = f"✅ <b>Готово!</b>\n\n"
    text += f"• Вступил: <b>{joined}</b>\n"
    text += f"• Уже был: <b>{already}</b>\n"
    if errors:
        text += f"\n⚠️ Ошибки ({len(errors)}):\n"
        text += "\n".join(errors[:15])

    await message.answer(text, parse_mode="HTML")
