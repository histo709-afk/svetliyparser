"""Handler for auto-creating a new city's parser destination channel."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

router = Router(name="new_city")


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


@router.message(Command("newcity"))
async def cmd_new_city(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer(
            "Использование: <code>/newcity Город</code>\n"
            "Создаст канал «Парсер Город» и зарегистрирует его как назначение."
        )
        return

    city = parts[1].strip()
    title = f"Парсер {city}"

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        existing = next(
            (d for d in await repo.list_all_destinations() if d.title == title),
            None,
        )
    if existing is not None:
        await message.answer(
            f"ℹ️ Канал «{title}» уже существует (ID <code>{existing.telegram_id}</code>)."
        )
        return

    await message.answer(f"⏳ Создаю канал «{title}»...")

    client = _get_telethon_client()
    try:
        result = await client(
            CreateChannelRequest(title=title, about="", megagroup=False, broadcast=True)
        )
        new_channel = result.chats[0]
        telegram_id = int(f"-100{new_channel.id}")
        invite = await client(ExportChatInviteRequest(peer=new_channel))
    except Exception as exc:
        await message.answer(f"❌ Не удалось создать канал: {exc}")
        return

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dest = await repo.add_destination(telegram_id=telegram_id, username=None, title=title)
        await session.commit()

    await message.answer(
        f"✅ Канал «{title}» создан и зарегистрирован!\n\n"
        f"ID: <code>{dest.telegram_id}</code>\n"
        f"Ссылка: {invite.link}\n\n"
        f"Теперь отправьте .xlsx со списком источников для этого города "
        f"(колонки «Источник» / «Назначение», где «Назначение» = <code>{invite.link}</code>) — "
        f"бот сам заджойнит каналы и построит маршруты."
    )
