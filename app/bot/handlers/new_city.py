"""Handler for auto-creating a new city's parser destination channel."""
from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from telethon.errors import UserPrivacyRestrictedError
from telethon.tl.functions.channels import CreateChannelRequest, EditAdminRequest, InviteToChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import ChatAdminRights

from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository

OWNER_USERNAME = "osnova_SMMsik"

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


OWNER_ADMIN_RIGHTS = ChatAdminRights(
    post_messages=True,
    edit_messages=True,
    delete_messages=True,
    invite_users=True,
    change_info=True,
    add_admins=True,
    anonymous=False,
    pin_messages=True,
    manage_call=True,
)


async def _add_owner_as_admin(client, channel_entity) -> bool:
    """Always invite the account owner (@BuLDoG000) into every newly created
    parser channel and grant full admin rights, so channels aren't left
    accessible only to the userbot/management-bot pair. Raises
    UserPrivacyRestrictedError as-is (caller distinguishes it from other
    failures) when the owner's Telegram privacy settings block being added
    by someone who isn't a mutual contact — that can't be worked around
    from this side, only from the owner's own privacy settings or by them
    joining the invite link themselves."""
    from telethon.errors import UserAlreadyParticipantError

    owner_entity = await client.get_entity(OWNER_USERNAME)

    try:
        await client(InviteToChannelRequest(channel=channel_entity, users=[owner_entity]))
    except UserAlreadyParticipantError:
        pass

    await client(EditAdminRequest(
        channel=channel_entity,
        user_id=owner_entity,
        admin_rights=OWNER_ADMIN_RIGHTS,
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
    owner_privacy_blocked = False
    try:
        owner_added = await _add_owner_as_admin(client, new_channel)
    except UserPrivacyRestrictedError:
        owner_privacy_blocked = True
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
    if owner_added:
        owner_line = f"👤 @{OWNER_USERNAME} добавлен с полными правами админа."
    elif owner_privacy_blocked:
        owner_line = (
            f"⚠️ Настройки приватности @{OWNER_USERNAME} не позволяют добавить его "
            f"силой. Перейди по ссылке выше и вступи сам, затем пропиши "
            f"<code>/promoteowner {telegram_id}</code> — права админа выдадутся автоматически."
        )
    else:
        owner_line = f"⚠️ Не удалось добавить @{OWNER_USERNAME} — добавь вручную."
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


@router.message(Command("promoteowner"))
async def cmd_promote_owner(message: Message) -> None:
    """Retry granting @OWNER_USERNAME full admin rights in a channel they've
    since joined themselves (e.g. after being blocked by privacy settings
    during /newcity). Usage: /promoteowner <telegram_id>"""
    parts = message.text.split() if message.text else []
    if len(parts) < 2:
        await message.answer(f"Использование: <code>/promoteowner ID_канала</code>", parse_mode="HTML")
        return

    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ ID канала должен быть числом.")
        return

    client = _get_telethon_client()
    try:
        channel_entity = await client.get_entity(telegram_id)
        owner_entity = await client.get_entity(OWNER_USERNAME)
        await client(EditAdminRequest(
            channel=channel_entity,
            user_id=owner_entity,
            admin_rights=OWNER_ADMIN_RIGHTS,
            rank="owner",
        ))
    except Exception as exc:
        await message.answer(f"❌ Не удалось выдать права: {exc}")
        return

    await message.answer(f"✅ @{OWNER_USERNAME} теперь админ с полными правами.")
