"""Status, routes, and log handlers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import back_to_menu_keyboard
from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.route_repo import RouteRepository
from app.services.channel_service import channel_display_name
from app.services.sync_service import get_last_errors

router = Router(name="status")


@router.message(Command("routes"))
@router.callback_query(F.data == "routes")
async def show_routes(event: Message | CallbackQuery, state: FSMContext) -> None:
    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        routes = await route_repo.list_all_routes()

    if not routes:
        text = "📭 Маршруты не настроены.\n\nДобавьте источник и назначение."
    else:
        lines = ["🔀 <b>Маршруты пересылки:</b>\n"]
        for r in routes:
            status = "✅" if r.is_active else "⏸ (деактивирован)"
            src_name = channel_display_name(r.source) if r.source else f"ID {r.source_id}"
            dst_name = channel_display_name(r.destination) if r.destination else f"ID {r.destination_id}"
            lines.append(f"{status}\n📥 {src_name}\n➡️ 📤 {dst_name}\n")
        text = "\n".join(lines)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


@router.message(Command("status"))
@router.callback_query(F.data == "status")
async def show_status(event: Message | CallbackQuery, state: FSMContext) -> None:
    async with async_session_factory() as session:
        channel_repo = ChannelRepository(session)
        route_repo = RouteRepository(session)
        msg_repo = MessageRepository(session)

        sources = await channel_repo.list_active_sources()
        dests = await channel_repo.list_active_destinations()
        routes = await route_repo.list_active_routes()
        today_count = await msg_repo.count_today()

    text = (
        "📊 <b>Статус системы</b>\n\n"
        f"📥 Источников: <b>{len(sources)}</b>\n"
        f"📤 Назначений: <b>{len(dests)}</b>\n"
        f"🔀 Активных маршрутов: <b>{len(routes)}</b>\n"
        f"📨 Переслано сегодня: <b>{today_count}</b>"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


@router.message(Command("logs"))
@router.callback_query(F.data == "logs")
async def show_logs(event: Message | CallbackQuery, state: FSMContext) -> None:
    errors = await get_last_errors(10)

    if not errors:
        text = "✅ Ошибок нет."
    else:
        lines = ["⚠️ <b>Последние ошибки:</b>\n"]
        for i, err in enumerate(errors, 1):
            lines.append(f"{i}. <code>{err[:200]}</code>")
        text = "\n".join(lines)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")


@router.message(Command("removeroute"))
async def cmd_remove_route(message: Message) -> None:
    """Deactivate a route by ID: /removeroute <route_id>"""
    parts = message.text.split() if message.text else []
    if len(parts) < 2 or not parts[1].isdigit():
        # List routes with IDs
        async with async_session_factory() as session:
            route_repo = RouteRepository(session)
            routes = await route_repo.list_active_routes()

        if not routes:
            await message.answer("Активных маршрутов нет.")
            return

        lines = ["Активные маршруты (укажите ID для удаления: /removeroute ID):\n"]
        for r in routes:
            src = channel_display_name(r.source) if r.source else f"source_id={r.source_id}"
            dst = channel_display_name(r.destination) if r.destination else f"dest_id={r.destination_id}"
            lines.append(f"ID {r.id}: {src} → {dst}")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    route_id = int(parts[1])
    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        ok = await route_repo.deactivate_route(route_id)
        await session.commit()

    if ok:
        await message.answer(f"✅ Маршрут #{route_id} деактивирован.")
    else:
        await message.answer(f"❌ Маршрут #{route_id} не найден.")
