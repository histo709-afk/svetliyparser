"""Handlers for adding/removing source channels."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import back_to_menu_keyboard, cancel_keyboard
from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services.channel_service import add_source_channel, add_destination_channel, channel_display_name, create_route

router = Router(name="sources")


class AddSourceStates(StatesGroup):
    waiting_link = State()
    waiting_dest_link = State()


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
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="HTML")


@router.message(Command("addsource"))
@router.callback_query(F.data == "add_source")
async def start_add_source(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddSourceStates.waiting_link)
    text = (
        "📥 <b>Добавление источника</b>\n\n"
        "Отправьте ссылку на канал-источник в любом формате:\n"
        "• <code>https://t.me/channel</code>\n"
        "• <code>@channel</code>\n"
        "• <code>channel</code>"
    )
    if isinstance(event, CallbackQuery):
        await state.update_data(prompt_msg_id=event.message.message_id,
                                prompt_chat_id=event.message.chat.id)
        await event.message.edit_text(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        sent = await event.answer(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
        await state.update_data(prompt_msg_id=sent.message_id, prompt_chat_id=event.chat.id)


@router.message(AddSourceStates.waiting_link)
async def process_source_link(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id") or message.chat.id

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
            channel, created = await add_source_channel(session, client, link)
            await session.commit()

        src_name = channel_display_name(channel)
        await state.update_data(src_channel_id=channel.id, src_name=src_name)
        await state.set_state(AddSourceStates.waiting_dest_link)

        prefix = "✅ Канал-источник добавлен!" if created else "ℹ️ Канал уже существует."
        await _edit_or_answer(
            message.bot, prompt_chat_id, prompt_msg_id,
            f"{prefix}\n\n<b>{src_name}</b>\n\n"
            f"Теперь отправьте ссылку на канал-назначение:\n"
            f"• <code>@channel</code>\n"
            f"• <code>https://t.me/channel</code>",
            cancel_keyboard(),
        )
        return

    except ValueError as exc:
        text = f"❌ Ошибка: {exc}"
    except Exception as exc:
        text = f"❌ Неожиданная ошибка: {exc}"

    await state.clear()
    await _edit_or_answer(message.bot, prompt_chat_id, prompt_msg_id,
                          text, back_to_menu_keyboard())


@router.message(AddSourceStates.waiting_dest_link)
async def process_dest_link_for_source(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id") or message.chat.id
    src_channel_id: int = data["src_channel_id"]
    src_name: str = data["src_name"]

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
            dest_channel, _ = await add_destination_channel(session, client, link)
            await session.commit()
            dest_id = dest_channel.id
            dest_name = channel_display_name(dest_channel)

        async with async_session_factory() as session:
            route, created = await create_route(session, src_channel_id, dest_id)
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


@router.message(Command("listsources"))
async def cmd_list_sources(message: Message) -> None:
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()

    if not sources:
        await message.answer("📭 Источники не добавлены.", reply_markup=back_to_menu_keyboard())
        return

    lines = []
    for s in sources:
        status = "✅" if s.is_active else "⏸"
        lines.append(f"{status} {channel_display_name(s)}")

    header = f"📋 <b>Источники ({len(sources)}):</b>\n\n"
    chunk, chunks = [], []
    for line in lines:
        chunk.append(line)
        if len(chunk) == 50:
            chunks.append(chunk)
            chunk = []
    if chunk:
        chunks.append(chunk)

    for i, ch in enumerate(chunks):
        text = (header if i == 0 else "") + "\n".join(ch)
        kb = back_to_menu_keyboard() if i == len(chunks) - 1 else None
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("removesource"))
async def cmd_remove_source(message: Message) -> None:
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer("Использование: /removesource @channel_name или ссылка")
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
            ok = await repo.deactivate_source(info.telegram_id)
            await session.commit()

        if ok:
            await message.answer(f"✅ Источник деактивирован: {info.title}")
        else:
            await message.answer("ℹ️ Такой источник не найден в базе.")
    except Exception as exc:
        await message.answer(f"❌ Ошибка: {exc}")
