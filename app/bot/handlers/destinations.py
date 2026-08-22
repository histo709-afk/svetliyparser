"""Handlers for adding/removing destination channels and creating routes."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import back_to_menu_keyboard, cancel_keyboard
from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services.channel_service import (
    add_destination_channel,
    add_source_channel,
    channel_display_name,
    create_route,
)

router = Router(name="destinations")


class AddDestStates(StatesGroup):
    waiting_link = State()
    waiting_source_link = State()


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


async def _try_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def _edit_or_answer(bot, chat_id: int, msg_id: int | None, text: str, markup) -> None:
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=markup, parse_mode="HTML",
            )
            return
        except Exception:
            pass
    # fallback: shouldn't happen normally
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML")


@router.message(Command("adddest"))
@router.callback_query(F.data == "add_dest")
async def start_add_dest(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddDestStates.waiting_link)
    text = (
        "📤 <b>Добавление назначения</b>\n\n"
        "Отправьте ссылку на канал-назначение:\n"
        "• <code>https://t.me/channel</code>\n"
        "• <code>@channel</code>\n"
        "• <code>channel</code>\n\n"
        "⚠️ Бот должен быть администратором в этом канале."
    )
    if isinstance(event, CallbackQuery):
        await state.update_data(prompt_msg_id=event.message.message_id,
                                prompt_chat_id=event.message.chat.id)
        await event.message.edit_text(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        sent = await event.answer(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
        await state.update_data(prompt_msg_id=sent.message_id, prompt_chat_id=event.chat.id)


@router.message(AddDestStates.waiting_link)
async def process_dest_link(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id") or message.chat.id

    await _try_delete(message)

    link = message.text.strip() if message.text else ""
    if not link:
        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              "⚠️ Пожалуйста, отправьте текстовую ссылку.", cancel_keyboard())
        return

    await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                          "🔍 Ищу канал...", None)

    try:
        client = _get_telethon_client()
        async with async_session_factory() as session:
            dest_channel, created = await add_destination_channel(session, client, link)
            await session.commit()
            dest_id = dest_channel.id
            dest_name = channel_display_name(dest_channel)

        await state.update_data(dest_channel_id=dest_id, dest_name=dest_name)
        await state.set_state(AddDestStates.waiting_source_link)

        prefix = "✅ Назначение добавлено!\n\n" if created else "ℹ️ Назначение уже существует.\n\n"
        await _edit_or_answer(
            message.bot, prompt_chat_id, prompt_msg_id,
            f"{prefix}<b>{dest_name}</b>\n\n"
            f"Теперь введите ссылку на канал-источник:\n"
            f"• <code>@channel</code>\n"
            f"• <code>https://t.me/channel</code>",
            cancel_keyboard(),
        )

    except ValueError as exc:
        await state.clear()
        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              f"❌ Ошибка: {exc}", back_to_menu_keyboard())
    except Exception as exc:
        await state.clear()
        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              f"❌ Неожиданная ошибка: {exc}", back_to_menu_keyboard())


@router.message(AddDestStates.waiting_source_link)
async def process_source_link_for_route(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id") or message.chat.id
    dest_channel_id: int = data["dest_channel_id"]
    dest_name: str = data["dest_name"]

    await _try_delete(message)

    link = message.text.strip() if message.text else ""
    if not link:
        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              "⚠️ Пожалуйста, отправьте текстовую ссылку.", cancel_keyboard())
        return

    await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id, "🔍 Ищу канал...", None)

    try:
        client = _get_telethon_client()
        async with async_session_factory() as session:
            src_channel, _ = await add_source_channel(session, client, link)
            await session.commit()
            src_id = src_channel.id
            src_name = channel_display_name(src_channel)

        async with async_session_factory() as session:
            route, created = await create_route(session, src_id, dest_channel_id)
            await session.commit()

        await state.clear()

        if created:
            text = f"✅ <b>Маршрут создан!</b>\n\n📥 {src_name}\n⬇️\n📤 {dest_name}"
        else:
            text = f"ℹ️ Маршрут уже существует:\n\n📥 {src_name}\n⬇️\n📤 {dest_name}"

        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              text, back_to_menu_keyboard())

    except ValueError as exc:
        await state.clear()
        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              f"❌ Ошибка: {exc}", back_to_menu_keyboard())
    except Exception as exc:
        await state.clear()
        await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                              f"❌ Неожиданная ошибка: {exc}", back_to_menu_keyboard())


@router.message(Command("listdests"))
async def cmd_list_dests(message: Message) -> None:
    """List every destination with a real t.me link. Public channels use
    their username directly; private ones (the common case — most
    destinations are invite-only "Парсер X" channels) get a fresh invite
    link exported live via the userbot, which is a member/admin of all of
    them — no stored link needed."""
    from telethon.tl.functions.messages import ExportChatInviteRequest

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dests = await repo.list_all_destinations()

    if not dests:
        await message.answer("📭 Назначения не добавлены.", reply_markup=back_to_menu_keyboard())
        return

    await message.answer(f"⏳ Собираю ссылки на {len(dests)} каналов...")

    client = _get_telethon_client()
    lines = ["📋 <b>Назначения:</b>\n"]
    for d in dests:
        status = "✅" if d.is_active else "⏸"
        name = d.title or channel_display_name(d)
        if d.username:
            link = f"https://t.me/{d.username}"
        else:
            try:
                invite = await client(ExportChatInviteRequest(peer=d.telegram_id))
                link = invite.link
            except Exception as exc:
                link = f"(не удалось получить ссылку: {str(exc)[:60]})"
        lines.append(f"{status} <b>{name}</b>\nID: <code>{d.telegram_id}</code>\n{link}")

    text = "\n\n".join(lines)
    for i in range(0, len(text), 3500):
        await message.answer(text[i:i + 3500], parse_mode="HTML", disable_web_page_preview=True)
    await message.answer("Готово.", reply_markup=back_to_menu_keyboard())


@router.message(Command("fixdesttitles"))
async def cmd_fix_dest_titles(message: Message) -> None:
    """Refresh every destination's stored title from its live Telethon
    entity. Fixes rows created with a garbage title (the raw invite hash
    instead of the real channel name) — a bug where a Redis-cached invite
    lookup skipped fetching the actual title; now fixed going forward, but
    existing rows created before the fix still need a one-time refresh."""
    client = _get_telethon_client()

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dests = await repo.list_all_destinations()

    updated = 0
    failed = 0
    async with async_session_factory() as session:
        from sqlalchemy import select
        from app.models.channel import DestinationChannel

        for d in dests:
            try:
                entity = await client.get_entity(d.telegram_id)
                real_title = getattr(entity, "title", None)
                if real_title and real_title != d.title:
                    result = await session.execute(
                        select(DestinationChannel).where(DestinationChannel.id == d.id)
                    )
                    row = result.scalar_one_or_none()
                    if row:
                        row.title = real_title
                        updated += 1
            except Exception:
                failed += 1
        await session.commit()

    await message.answer(
        f"✅ Обновлено названий: <b>{updated}</b>\n⚠️ Не удалось получить: <b>{failed}</b>",
        parse_mode="HTML",
    )


@router.message(Command("removedest"))
async def cmd_remove_dest(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer("Использование: /removedest @channel_name или ссылка")
        return

    link = parts[1].strip()
    try:
        client = _get_telethon_client()
        from app.services.channel_service import resolve_channel
        info = await resolve_channel(client, link)
        if info is None:
            await message.answer("❌ Канал не найден.")
            return

        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            ok = await repo.deactivate_destination(info.telegram_id)
            await session.commit()

        if ok:
            await message.answer(f"✅ Назначение деактивировано: {info.title}")
        else:
            await message.answer("ℹ️ Такое назначение не найдено в базе.")
    except Exception as exc:
        await message.answer(f"❌ Ошибка: {exc}")
