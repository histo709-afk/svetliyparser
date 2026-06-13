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
        identifier = src.username if src.username else None
        if not identifier:
            already += 1  # skip channels without username
            continue
        try:
            entity = await telethon_client.get_entity(identifier)
            try:
                from telethon.tl.functions.channels import JoinChannelRequest
                from telethon.errors import FloodWaitError, UserAlreadyParticipantError
                await telethon_client(JoinChannelRequest(entity))
                joined += 1
            except UserAlreadyParticipantError:
                already += 1
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 2)
                try:
                    await telethon_client(JoinChannelRequest(entity))
                    joined += 1
                except Exception:
                    already += 1  # assume already joined or skip
            except Exception as e:
                err_str = str(e)
                if "already" in err_str.lower():
                    already += 1
                else:
                    errors.append(f"{identifier}: {str(e)[:40]}")
        except Exception as e:
            errors.append(f"{identifier}: {str(e)[:40]}")

        await asyncio.sleep(2)

    text = f"✅ <b>Готово!</b>\n\n"
    text += f"• Вступил: <b>{joined}</b>\n"
    text += f"• Уже был: <b>{already}</b>\n"
    if errors:
        text += f"\n⚠️ Ошибки ({len(errors)}):\n"
        text += "\n".join(errors[:15])

    await message.answer(text, parse_mode="HTML")
