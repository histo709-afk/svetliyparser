"""Handler for auto-creating a new city's parser destination channel."""
from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, InviteToChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import ChatAdminRights

OWNER_USERNAME = "BuLDoG000"

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

router = Router(name="new_city")
log = structlog.get_logger(__name__)


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


async def _promote_bot_as_admin(client, channel_entity) -> bool:
    """Forwarding goes out via the Bot API (BOT_TOKEN), not this Telethon
    userbot session — a channel the userbot merely created is invisible to
    that bot until it's added as admin. Without this, /newcity would
    produce a destination nothing can ever actually be posted to."""
    from app.config import settings
    from aiogram import Bot

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        me = await bot.get_me()
    finally:
        await bot.session.close()

    bot_entity = await client.get_entity(me.username)
    await client(EditAdminRequest(
        channel=channel_entity,
        user_id=bot_entity,
        admin_rights=ChatAdminRights(
            post_messages=True,
            edit_messages=True,
            delete_messages=True,
            invite_users=True,
            change_info=False,
            add_admins=False,
            anonymous=False,
            pin_messages=True,
            manage_call=False,
        ),
        rank="parser",
    ))
    return True


async def _add_owner_as_admin(client, channel_entity) -> bool:
    """Always invite the account owner (@BuLDoG000) into every newly created
    parser channel and grant full admin rights, so channels aren't left
    accessible only to the userbot/management-bot pair."""
    from telethon.errors import UserAlreadyParticipantError

    owner_entity = await client.get_entity(OWNER_USERNAME)

    try:
        await client(InviteToChannelRequest(channel=channel_entity, users=[owner_entity]))
    except UserAlreadyParticipantError:
        pass

    await client(EditAdminRequest(
        channel=channel_entity,
        user_id=owner_entity,
        admin_rights=ChatAdminRights(
            post_messages=True,
            edit_messages=True,
            delete_messages=True,
            invite_users=True,
            change_info=True,
            add_admins=True,
            anonymous=False,
            pin_messages=True,
            manage_call=True,
        ),
        rank="owner",
    ))
    return True


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

    bot_promoted = False
    try:
        bot_promoted = await _promote_bot_as_admin(client, new_channel)
    except Exception as exc:
        log.error("newcity_bot_promote_failed", channel=telegram_id, error=str(exc))

    owner_added = False
    try:
        owner_added = await _add_owner_as_admin(client, new_channel)
    except Exception as exc:
        log.error("newcity_owner_add_failed", channel=telegram_id, error=str(exc))

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dest = await repo.add_destination(telegram_id=telegram_id, username=None, title=title)
        await session.commit()

    admin_line = (
        "🤖 Управляющий бот добавлен админом автоматически."
        if bot_promoted else
        "⚠️ Не удалось автоматически сделать управляющего бота админом — "
        "добавь <b>@Bot_Cloud_parserTG_bot</b> в администраторы канала вручную, "
        "иначе пересылка постов работать не будет."
    )
    owner_line = (
        f"👤 @{OWNER_USERNAME} добавлен с полными правами админа."
        if owner_added else
        f"⚠️ Не удалось добавить @{OWNER_USERNAME} — добавь вручную."
    )
    await message.answer(
        f"✅ Канал «{title}» создан и зарегистрирован!\n\n"
        f"ID: <code>{dest.telegram_id}</code>\n"
        f"Ссылка: {invite.link}\n"
        f"{admin_line}\n"
        f"{owner_line}\n\n"
        f"Теперь отправьте .xlsx со списком источников для этого города "
        f"(колонки «Источник» / «Назначение», где «Назначение» = <code>{invite.link}</code>) — "
        f"бот сам заджойнит каналы и построит маршруты."
    )
