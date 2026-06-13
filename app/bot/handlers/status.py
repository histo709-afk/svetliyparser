"""Status, routes, and log handlers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    back_to_menu_keyboard,
    confirm_delete_keyboard,
    route_actions_keyboard,
    routes_list_keyboard,
)
from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.route_repo import RouteRepository
from app.services.channel_service import channel_display_name
from app.services.sync_service import get_last_errors

router = Router(name="status")


async def _routes_page_text(routes: list, page: int) -> str:
    PAGE_SIZE = 10
    total = len(routes)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return (
        f"🔀 <b>Маршруты пересылки</b>\n\n"
        f"Всего: <b>{total}</b> | Страница {page + 1}/{total_pages}\n\n"
        "Нажмите 🗑 рядом с маршрутом для удаления."
    )


@router.message(Command("routes"))
@router.callback_query(F.data == "routes")
async def show_routes(event: Message | CallbackQuery, state: FSMContext) -> None:
    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        routes = await route_repo.list_all_routes()

    if not routes:
        text = "📭 Маршруты не настроены.\n\nДобавьте источник и назначение."
        kb = back_to_menu_keyboard()
    else:
        text = await _routes_page_text(routes, 0)
        kb = routes_list_keyboard(routes, 0)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("routes_page:"))
async def routes_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        routes = await route_repo.list_all_routes()

    if not routes:
        await callback.message.edit_text("📭 Маршруты не настроены.", reply_markup=back_to_menu_keyboard())
        await callback.answer()
        return

    text = await _routes_page_text(routes, page)
    await callback.message.edit_text(text, reply_markup=routes_list_keyboard(routes, page), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("route_info:"))
async def route_info(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        route = await route_repo.get_route_by_id(route_id)

    if route is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    src_name = channel_display_name(route.source) if route.source else f"ID {route.source_id}"
    dst_name = channel_display_name(route.destination) if route.destination else f"ID {route.destination_id}"
    status = "✅ Активен" if route.is_active else "⏸ Деактивирован"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {src_name}\n"
        f"📤 <b>Назначение:</b> {dst_name}\n"
        f"Статус: {status}"
    )
    await callback.message.edit_text(text, reply_markup=route_actions_keyboard(route_id, page), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("delete_route:"))
async def delete_route_prompt(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        route = await route_repo.get_route_by_id(route_id)

    if route is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    src_name = channel_display_name(route.source) if route.source else f"ID {route.source_id}"
    dst_name = channel_display_name(route.destination) if route.destination else f"ID {route.destination_id}"
    text = (
        f"⚠️ <b>Удалить маршрут #{route.id}?</b>\n\n"
        f"📥 {src_name}\n"
        f"📤 {dst_name}\n\n"
        "Это действие деактивирует маршрут."
    )
    await callback.message.edit_text(text, reply_markup=confirm_delete_keyboard(route_id, page), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_route:"))
async def confirm_delete_route(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        route = await route_repo.get_route_by_id(route_id)

    if route is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    src_name = channel_display_name(route.source) if route.source else f"ID {route.source_id}"
    dst_name = channel_display_name(route.destination) if route.destination else f"ID {route.destination_id}"
    text = (
        f"⚠️ <b>Удалить маршрут #{route.id}?</b>\n\n"
        f"📥 {src_name}\n"
        f"📤 {dst_name}\n\n"
        "Это действие деактивирует маршрут."
    )
    await callback.message.edit_text(text, reply_markup=confirm_delete_keyboard(route_id, page), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("do_delete_route:"))
async def do_delete_route(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0

    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        ok = await route_repo.deactivate_route(route_id)
        await session.commit()

    if not ok:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    await callback.answer(f"✅ Маршрут #{route_id} удалён.", show_alert=True)

    # Return to routes list
    async with async_session_factory() as session:
        route_repo = RouteRepository(session)
        routes = await route_repo.list_all_routes()

    if not routes:
        await callback.message.edit_text("📭 Маршруты не настроены.", reply_markup=back_to_menu_keyboard())
        return

    # Adjust page if needed
    PAGE_SIZE = 10
    max_page = max(0, (len(routes) - 1) // PAGE_SIZE)
    page = min(page, max_page)
    text = await _routes_page_text(routes, page)
    await callback.message.edit_text(text, reply_markup=routes_list_keyboard(routes, page), parse_mode="HTML")


@router.message(Command("debugsource"))
async def cmd_debug_source(message: Message) -> None:
    """Show telegram_id stored in DB for a source by username."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer("Использование: /debugsource @username или часть названия")
        return
    query = parts[1].strip().lstrip("@").lower()
    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()
    matches = [s for s in sources if query in (s.username or "").lower() or query in (s.title or "").lower()]
    if not matches:
        await message.answer(f"Источник '{query}' не найден.")
        return
    lines = []
    for s in matches:
        lines.append(f"<b>{s.title}</b>\n@{s.username}\ntelegram_id: <code>{s.telegram_id}</code>\nactive: {s.is_active}")
    await message.answer("\n\n".join(lines), parse_mode="HTML")


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
