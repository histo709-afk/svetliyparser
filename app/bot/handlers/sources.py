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
from app.services.channel_service import add_source_channel, channel_display_name

router = Router(name="sources")


class AddSourceStates(StatesGroup):
    waiting_link = State()


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


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
        await event.message.edit_text(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=cancel_keyboard(), parse_mode="HTML")


@router.message(AddSourceStates.waiting_link)
async def process_source_link(message: Message, state: FSMContext) -> None:
    link = message.text.strip() if message.text else ""
    if not link:
        await message.answer("⚠️ Пожалуйста, отправьте текстовую ссылку.")
        return

    await message.answer("🔍 Ищу канал...")

    try:
        client = _get_telethon_client()
        async with async_session_factory() as session:
            channel, created = await add_source_channel(session, client, link)
            await session.commit()

        if created:
            text = (
                f"✅ Канал-источник добавлен!\n\n"
                f"<b>{channel_display_name(channel)}</b>\n\n"
                f"Теперь добавьте канал-назначение командой /adddest"
            )
        else:
            text = (
                f"ℹ️ Канал уже существует:\n\n"
                f"<b>{channel_display_name(channel)}</b>"
            )
    except ValueError as exc:
        text = f"❌ Ошибка: {exc}"
    except Exception as exc:
        text = f"❌ Неожиданная ошибка: {exc}"

    await state.clear()
    await message.answer(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


@router.message(Command("listsources"))
async def cmd_list_sources(message: Message) -> None:
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()

    if not sources:
        await message.answer("📭 Источники не добавлены.", reply_markup=back_to_menu_keyboard())
        return

    lines = ["📋 <b>Источники:</b>\n"]
    for s in sources:
        status = "✅" if s.is_active else "⏸"
        lines.append(f"{status} {channel_display_name(s)}")

    await message.answer("\n".join(lines), reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


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
