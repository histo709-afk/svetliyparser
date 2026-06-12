"""Handlers for adding/removing destination channels and creating routes."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    back_to_menu_keyboard,
    cancel_keyboard,
    source_selection_keyboard,
)
from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.services.channel_service import (
    add_destination_channel,
    channel_display_name,
    create_route,
)

router = Router(name="destinations")


class AddDestStates(StatesGroup):
    waiting_link = State()
    waiting_source_selection = State()


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


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
        await event.message.edit_text(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=cancel_keyboard(), parse_mode="HTML")


@router.message(AddDestStates.waiting_link)
async def process_dest_link(message: Message, state: FSMContext) -> None:
    link = message.text.strip() if message.text else ""
    if not link:
        await message.answer("⚠️ Пожалуйста, отправьте текстовую ссылку.")
        return

    await message.answer("🔍 Ищу канал...")

    try:
        client = _get_telethon_client()
        async with async_session_factory() as session:
            dest_channel, created = await add_destination_channel(session, client, link)
            await session.commit()
            dest_id = dest_channel.id
            dest_name = channel_display_name(dest_channel)

        # Now ask which source to link
        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            sources = await repo.list_active_sources()

        if not sources:
            await state.clear()
            if created:
                text = (
                    f"✅ Назначение добавлено: <b>{dest_name}</b>\n\n"
                    f"ℹ️ Источники не найдены. Добавьте источник: /addsource"
                )
            else:
                text = f"ℹ️ Назначение уже существует: <b>{dest_name}</b>\n\nИсточники не найдены."
            await message.answer(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
            return

        await state.update_data(dest_channel_id=dest_id, dest_name=dest_name)
        await state.set_state(AddDestStates.waiting_source_selection)

        prefix = "✅ Назначение добавлено!\n\n" if created else "ℹ️ Назначение уже существует.\n\n"
        await message.answer(
            f"{prefix}<b>{dest_name}</b>\n\nВыберите источник для этого маршрута:",
            reply_markup=source_selection_keyboard(sources),
            parse_mode="HTML",
        )

    except ValueError as exc:
        await state.clear()
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=back_to_menu_keyboard())
    except Exception as exc:
        await state.clear()
        await message.answer(f"❌ Неожиданная ошибка: {exc}", reply_markup=back_to_menu_keyboard())


@router.callback_query(AddDestStates.waiting_source_selection, F.data.startswith("src_page:"))
async def paginate_sources(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()
    data = await state.get_data()
    dest_name = data.get("dest_name", "")
    await callback.message.edit_reply_markup(reply_markup=source_selection_keyboard(sources, page))
    await callback.answer()


@router.callback_query(AddDestStates.waiting_source_selection, F.data.startswith("select_source:"))
async def process_source_selection(callback: CallbackQuery, state: FSMContext) -> None:
    source_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    dest_channel_id: int = data["dest_channel_id"]
    dest_name: str = data["dest_name"]

    await state.clear()

    try:
        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            source = await repo.get_source_by_id(source_id)
            if source is None:
                await callback.message.edit_text("❌ Источник не найден.", reply_markup=back_to_menu_keyboard())
                await callback.answer()
                return

            src_name = channel_display_name(source)
            route, created = await create_route(session, source_id, dest_channel_id)
            await session.commit()

        if created:
            text = (
                f"✅ <b>Маршрут создан!</b>\n\n"
                f"📥 {src_name}\n"
                f"⬇️\n"
                f"📤 {dest_name}"
            )
        else:
            text = (
                f"ℹ️ Маршрут уже существует:\n\n"
                f"📥 {src_name}\n"
                f"⬇️\n"
                f"📤 {dest_name}"
            )
    except Exception as exc:
        text = f"❌ Ошибка создания маршрута: {exc}"

    await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(Command("listdests"))
async def cmd_list_dests(message: Message) -> None:
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        dests = await repo.list_all_destinations()

    if not dests:
        await message.answer("📭 Назначения не добавлены.", reply_markup=back_to_menu_keyboard())
        return

    lines = ["📋 <b>Назначения:</b>\n"]
    for d in dests:
        status = "✅" if d.is_active else "⏸"
        lines.append(f"{status} {channel_display_name(d)}")

    await message.answer("\n".join(lines), reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


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
