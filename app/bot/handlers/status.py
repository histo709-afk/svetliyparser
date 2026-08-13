"""Status, routes, and log handlers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    back_to_menu_keyboard,
    confirm_delete_route_keyboard,
    route_actions_keyboard,
    route_search_results_keyboard,
    routes_filter_keyboard,
    routes_list_keyboard,
)
from app.database import async_session_factory
from app.repositories.channel_repo import ChannelRepository
from app.repositories.message_repo import MessageRepository
from app.repositories.route_repo import RouteRepository
from app.services.channel_service import channel_display_name
from app.services.sync_service import get_last_errors, reset_last_seen

router = Router(name="status")


def _route_label(route) -> str:
    src = channel_display_name(route.source) if route.source else f"ID {route.source_id}"
    dst = channel_display_name(route.destination) if route.destination else f"ID {route.destination_id}"
    return f"{src} → {dst}"


# ── ROUTES ENTRY ──────────────────────────────────────────────────────────────

@router.message(Command("routes"))
@router.callback_query(F.data == "routes")
async def show_routes(event: Message | CallbackQuery, state: FSMContext) -> None:
    text = "🔀 <b>Маршруты пересылки</b>\n\nВыберите фильтр:"
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=routes_filter_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=routes_filter_keyboard(), parse_mode="HTML")


# ── SEARCH ────────────────────────────────────────────────────────────────────

class RouteSearchStates(StatesGroup):
    waiting_query = State()


@router.callback_query(F.data == "routes_search")
async def routes_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RouteSearchStates.waiting_query)
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="routes"))
    await callback.message.edit_text(
        "🔍 <b>Поиск маршрута</b>\n\n"
        "Напишите название города, района или канала (источника или назначения):",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RouteSearchStates.waiting_query)
async def routes_search_result(message: Message, state: FSMContext) -> None:
    query = (message.text or "").strip().lower().lstrip("@")
    await state.clear()

    if len(query) < 2:
        await message.answer("Слишком короткий запрос, попробуй снова через «🔍 Поиск».")
        return

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        routes = await repo.list_all_routes()

    matches = [
        r for r in routes
        if (r.source and query in channel_display_name(r.source).lower())
        or (r.destination and query in channel_display_name(r.destination).lower())
    ]

    if not matches:
        b_builder = routes_filter_keyboard()
        await message.answer(f"По запросу «{message.text.strip()}» маршрутов не найдено.", reply_markup=b_builder)
        return

    total = len(matches)
    # Telegram caps inline keyboards at 100 buttons; stay well under that.
    SAFETY_CAP = 90
    shown = matches[:SAFETY_CAP]
    text = f"🔍 <b>Найдено маршрутов: {total}</b>" + (f" (показаны первые {len(shown)})" if total > len(shown) else "")
    await message.answer(text, reply_markup=route_search_results_keyboard(shown), parse_mode="HTML")


# ── FILTERED LIST ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("routes_filter:"))
async def routes_filter(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    filter_ = parts[1]  # "active" or "stopped"
    page = int(parts[2]) if len(parts) > 2 else 0

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        if filter_ == "stopped":
            routes = await repo.list_stopped_routes()
            title = "⏸ <b>Остановленные маршруты</b>"
        else:
            routes = await repo.list_active_routes()
            title = "▶️ <b>Запущенные маршруты</b>"

    if not routes:
        empty = "Запущенных маршрутов нет." if filter_ == "active" else "Остановленных маршрутов нет."
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="routes"))
        await callback.message.edit_text(empty, reply_markup=b.as_markup())
        await callback.answer()
        return

    PAGE_SIZE = 10
    total = len(routes)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    text = f"{title}\n\nВсего: <b>{total}</b> | Стр. {page + 1}/{total_pages}"
    await callback.message.edit_text(
        text,
        reply_markup=routes_list_keyboard(routes, page, filter_),
        parse_mode="HTML",
    )
    await callback.answer()


# ── ROUTE INFO (settings page) ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("route_info:"))
async def route_info(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "active"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        route = await repo.get_route_by_id(route_id)

    if route is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    status = "▶️ Запущен" if route.is_active else "⏸ Остановлен"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {channel_display_name(route.source) if route.source else route.source_id}\n"
        f"📤 <b>Назначение:</b> {channel_display_name(route.destination) if route.destination else route.destination_id}\n\n"
        f"Статус: <b>{status}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, getattr(route, "strip_footer", False), getattr(route, "media_only", False)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("route"))
async def cmd_open_route(message: Message) -> None:
    """Open a route's settings menu directly.
    Usage: /route <ID>                — open by numeric route ID
           /route <часть названия>    — search by source/destination name/username"""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) < 2:
        await message.answer("Использование:\n<code>/route ID</code> или <code>/route часть_названия</code>", parse_mode="HTML")
        return

    query = parts[1].strip()

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        if query.isdigit():
            route = await repo.get_route_by_id(int(query))
            matches = [route] if route else []
        else:
            routes = await repo.list_all_routes()
            q = query.lower().lstrip("@")
            matches = [
                r for r in routes
                if (r.source and q in (channel_display_name(r.source)).lower())
                or (r.destination and q in (channel_display_name(r.destination)).lower())
            ]

    if not matches:
        await message.answer(f"Маршрут по запросу «{query}» не найден.")
        return

    if len(matches) > 1:
        lines = ["Найдено несколько маршрутов, уточни ID:\n"]
        for r in matches[:15]:
            lines.append(f"#{r.id}: {_route_label(r)}")
        await message.answer("\n".join(lines))
        return

    route = matches[0]
    status = "▶️ Запущен" if route.is_active else "⏸ Остановлен"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {channel_display_name(route.source) if route.source else route.source_id}\n"
        f"📤 <b>Назначение:</b> {channel_display_name(route.destination) if route.destination else route.destination_id}\n\n"
        f"Статус: <b>{status}</b>"
    )
    filter_ = "active" if route.is_active else "stopped"
    await message.answer(
        text,
        reply_markup=route_actions_keyboard(route.id, 0, filter_, route.is_active, getattr(route, "strip_footer", False), getattr(route, "media_only", False)),
        parse_mode="HTML",
    )


# ── STOP / START ──────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("route_stop:"))
async def route_stop(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "active"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        ok = await repo.deactivate_route(route_id)
        await session.commit()

    if not ok:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    await callback.answer("⏸ Маршрут остановлен.")

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        route = await repo.get_route_by_id(route_id)

    if route is None:
        await callback.message.edit_text("Маршрут не найден.", reply_markup=back_to_menu_keyboard())
        return

    status = "▶️ Запущен" if route.is_active else "⏸ Остановлен"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {channel_display_name(route.source) if route.source else route.source_id}\n"
        f"📤 <b>Назначение:</b> {channel_display_name(route.destination) if route.destination else route.destination_id}\n\n"
        f"Статус: <b>{status}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, getattr(route, "strip_footer", False), getattr(route, "media_only", False)),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("route_start:"))
async def route_start(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "stopped"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        ok = await repo.activate_route(route_id)
        await session.commit()

    if not ok:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    await callback.answer("▶️ Маршрут запущен.")

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        route = await repo.get_route_by_id(route_id)

    if route is None:
        await callback.message.edit_text("Маршрут не найден.", reply_markup=back_to_menu_keyboard())
        return

    status = "▶️ Запущен" if route.is_active else "⏸ Остановлен"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {channel_display_name(route.source) if route.source else route.source_id}\n"
        f"📤 <b>Назначение:</b> {channel_display_name(route.destination) if route.destination else route.destination_id}\n\n"
        f"Статус: <b>{status}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, getattr(route, "strip_footer", False), getattr(route, "media_only", False)),
        parse_mode="HTML",
    )


# ── TOGGLE STRIP FOOTER ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("route_toggle_footer:"))
async def route_toggle_footer(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "active"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        new_val = await repo.toggle_strip_footer(route_id)
        await session.commit()

    if new_val is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    await callback.answer("✅ Включено" if new_val else "☑️ Выключено")

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        route = await repo.get_route_by_id(route_id)

    if route is None:
        return

    status = "▶️ Запущен" if route.is_active else "⏸ Остановлен"
    footer_status = "✅ включено" if route.strip_footer else "выключено"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {channel_display_name(route.source) if route.source else route.source_id}\n"
        f"📤 <b>Назначение:</b> {channel_display_name(route.destination) if route.destination else route.destination_id}\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Авто-удаление плашки: <b>{footer_status}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, route.strip_footer, route.media_only),
        parse_mode="HTML",
    )


# ── TOGGLE MEDIA ONLY ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("route_toggle_media_only:"))
async def route_toggle_media_only(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "active"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        new_val = await repo.toggle_media_only(route_id)
        await session.commit()

    if new_val is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    await callback.answer("✅ Включено" if new_val else "☑️ Выключено")

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        route = await repo.get_route_by_id(route_id)

    if route is None:
        return

    status = "▶️ Запущен" if route.is_active else "⏸ Остановлен"
    media_status = "✅ включено" if route.media_only else "выключено"
    text = (
        f"🔀 <b>Маршрут #{route.id}</b>\n\n"
        f"📥 <b>Источник:</b> {channel_display_name(route.source) if route.source else route.source_id}\n"
        f"📤 <b>Назначение:</b> {channel_display_name(route.destination) if route.destination else route.destination_id}\n\n"
        f"Статус: <b>{status}</b>\n"
        f"Только посты с фото/видео: <b>{media_status}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, route.strip_footer, route.media_only),
        parse_mode="HTML",
    )


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("delete_route:"))
async def delete_route_prompt(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "active"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        route = await repo.get_route_by_id(route_id)

    if route is None:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    label = _route_label(route)
    text = (
        f"⚠️ <b>Удалить маршрут?</b>\n\n"
        f"<b>{label}</b>\n\n"
        f"Маршрут будет удалён полностью. Вы уверены?"
    )
    await callback.message.edit_text(
        text,
        reply_markup=confirm_delete_route_keyboard(route_id, page, filter_),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("do_delete_route:"))
async def do_delete_route(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    route_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    filter_ = parts[3] if len(parts) > 3 else "active"

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        ok = await repo.delete_route(route_id)
        await session.commit()

    if not ok:
        await callback.answer("Маршрут не найден.", show_alert=True)
        return

    await callback.answer(f"✅ Маршрут #{route_id} удалён.", show_alert=True)

    async with async_session_factory() as session:
        repo = RouteRepository(session)
        if filter_ == "stopped":
            routes = await repo.list_stopped_routes()
        else:
            routes = await repo.list_active_routes()

    if not routes:
        await callback.message.edit_text(
            "🔀 <b>Маршруты пересылки</b>\n\nВыберите фильтр:",
            reply_markup=routes_filter_keyboard(),
            parse_mode="HTML",
        )
        return

    PAGE_SIZE = 10
    max_page = max(0, (len(routes) - 1) // PAGE_SIZE)
    page = min(page, max_page)
    total = len(routes)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    title = "▶️ <b>Запущенные маршруты</b>" if filter_ == "active" else "⏸ <b>Остановленные маршруты</b>"
    text = f"{title}\n\nВсего: <b>{total}</b> | Стр. {page + 1}/{total_pages}"
    await callback.message.edit_text(
        text,
        reply_markup=routes_list_keyboard(routes, page, filter_),
        parse_mode="HTML",
    )


# ── ARCHIVE ───────────────────────────────────────────────────────────────────

def _channel_link(title: str | None, username: str | None, fallback: str) -> str:
    name = title or username or fallback
    if username:
        return f'<a href="https://t.me/{username}">{name}</a>'
    return name


@router.callback_query(F.data == "routes_archive")
async def routes_archive(callback: CallbackQuery) -> None:
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🗑 Удалённые", callback_data="archive_deleted"),
        InlineKeyboardButton(text="🕓 Добавленные ранее", callback_data="archive_added"),
    )
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="routes"))
    await callback.message.edit_text(
        "🗄 <b>Архив маршрутов</b>\n\n"
        "Здесь вы можете посмотреть добавленные ранее или удалённые маршруты.",
        reply_markup=b.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "archive_deleted")
async def archive_deleted(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        repo = RouteRepository(session)
        routes = await repo.list_deleted_routes()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="routes_archive"))

    if not routes:
        text = "🗑 <b>Удалённые маршруты</b>\n\nУдалённых маршрутов нет."
    else:
        lines = [f"🗑 <b>Удалённые маршруты</b> ({len(routes)}):\n"]
        for r in routes:
            src_title = r.source.title if r.source else None
            src_user = r.source.username if r.source else None
            dst_title = r.destination.title if r.destination else None
            dst_user = r.destination.username if r.destination else None
            src_link = _channel_link(src_title, src_user, f"src#{r.source_id}")
            dst_link = _channel_link(dst_title, dst_user, f"dst#{r.destination_id}")
            deleted = r.deleted_at.strftime("%d.%m.%Y") if r.deleted_at else "?"
            lines.append(f"• {src_link} → {dst_link} <i>(удалён {deleted})</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML",
                                     disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == "archive_added")
async def archive_added(callback: CallbackQuery) -> None:
    async with async_session_factory() as session:
        repo = RouteRepository(session)
        routes = await repo.list_recently_added(limit=20)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="◀️ Назад", callback_data="routes_archive"))

    if not routes:
        text = "🕓 <b>Добавленные ранее маршруты</b>\n\nМаршрутов нет."
    else:
        lines = [f"🕓 <b>Последние {len(routes)} маршрутов</b>:\n"]
        for r in routes:
            src_title = r.source.title if r.source else None
            src_user = r.source.username if r.source else None
            dst_title = r.destination.title if r.destination else None
            dst_user = r.destination.username if r.destination else None
            src_link = _channel_link(src_title, src_user, f"src#{r.source_id}")
            dst_link = _channel_link(dst_title, dst_user, f"dst#{r.destination_id}")
            added = r.created_at.strftime("%d.%m.%Y") if r.created_at else "?"
            status = "▶️" if r.is_active else "⏸"
            lines.append(f"{status} {src_link} → {dst_link} <i>({added})</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML",
                                     disable_web_page_preview=True)
    await callback.answer()


# ── STATUS ────────────────────────────────────────────────────────────────────

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


# ── LOGS ──────────────────────────────────────────────────────────────────────

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


# ── DEBUG / MANAGEMENT COMMANDS ───────────────────────────────────────────────

@router.message(Command("debugsource"))
async def cmd_debug_source(message: Message) -> None:
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


@router.message(Command("removeroute"))
async def cmd_remove_route(message: Message) -> None:
    parts = message.text.split() if message.text else []
    if len(parts) < 2 or not parts[1].isdigit():
        async with async_session_factory() as session:
            repo = RouteRepository(session)
            routes = await repo.list_active_routes()
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
        repo = RouteRepository(session)
        ok = await repo.deactivate_route(route_id)
        await session.commit()

    if ok:
        await message.answer(f"✅ Маршрут #{route_id} деактивирован.")
    else:
        await message.answer(f"❌ Маршрут #{route_id} не найден.")


@router.message(Command("resync"))
async def cmd_resync(message: Message) -> None:
    """Reset _last_seen for all (or specific) channels so next poll picks up recent messages.
    Usage: /resync            — reset all channels
           /resync @username  — reset one channel by username
    Dedup via synced_messages prevents double-posting."""
    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) > 1:
        query = parts[1].strip().lstrip("@").lower()
        async with async_session_factory() as session:
            repo = ChannelRepository(session)
            sources = await repo.list_all_sources()
        matches = [s for s in sources if query in (s.username or "").lower() or query in (s.title or "").lower()]
        if not matches:
            await message.answer(f"Источник '{query}' не найден.")
            return
        tids = [s.telegram_id for s in matches]
        count = reset_last_seen(tids)
        names = ", ".join(s.title or s.username or str(s.telegram_id) for s in matches)
        await message.answer(f"🔄 Сброшено <b>{count}</b> каналов: {names}\nСледующий цикл опроса подхватит последние посты.", parse_mode="HTML")
    else:
        count = reset_last_seen()
        await message.answer(f"🔄 Сброшено <b>{count}</b> каналов. Следующий цикл опроса (через ~30 сек) подхватит последние посты.", parse_mode="HTML")


@router.message(Command("joinall"))
async def cmd_joinall(message: Message) -> None:
    """Make the userbot account (re)join every active source channel — by
    @username when available, by its stored invite link otherwise. Guards
    against routes existing in the DB without real membership: a public
    channel resolves by username even if the join itself silently failed
    (e.g. hit a flood wait), so a route can look fine while the account was
    never actually admitted — this fixes that regardless of which one
    happened. Optional filter: /joinall лениногорск"""
    import asyncio
    from app.telethon_client.client import telethon_client
    from app.services.channel_service import join_channel_link

    parts = message.text.split(maxsplit=1) if message.text else []
    query = parts[1].strip().lstrip("@").lower() if len(parts) > 1 else None

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_active_sources()

    candidates = [s for s in sources if s.username or s.invite_link]
    no_link = [s for s in sources if not s.username and not s.invite_link]
    if query:
        candidates = [s for s in candidates if query in (s.username or "").lower() or query in (s.title or "").lower()]
        no_link = [s for s in no_link if query in (s.title or "").lower()]

    if not candidates:
        await message.answer("Нет источников с username или сохранённой инвайт-ссылкой для вступления.")
        return

    # Skip channels the account already knows about (in its dialog list) —
    # JoinChannelRequest against an already-member channel still counts
    # toward Telegram's join-flood limit in practice, so blasting it at
    # everyone (not just genuinely missing channels) triggers multi-minute
    # FloodWaitErrors per channel and can turn a few real joins into hours.
    try:
        dialogs = await telethon_client.get_dialogs(limit=None)
        known_ids = {d.entity.id for d in dialogs if hasattr(d, "entity")}
        # Telethon dialog entity IDs are unsigned; our stored IDs are the
        # full -100xxxxxxxxxx form — compare against both encodings.
        known_full_ids = known_ids | {int(f"-100{eid}") for eid in known_ids}
    except Exception:
        known_full_ids = set()

    targets = [s for s in candidates if s.telegram_id not in known_full_ids]
    already_known = len(candidates) - len(targets)

    if not targets:
        await message.answer(
            f"✅ Все {len(candidates)} каналов уже есть в диалогах аккаунта — вступать некуда.",
            parse_mode="HTML",
        )
        return

    await message.answer(
        f"🔗 Пропущено (уже в диалогах): <b>{already_known}</b>\n"
        f"Вступаю в <b>{len(targets)}</b> недостающих каналов, это может занять время из-за лимитов Telegram...",
        parse_mode="HTML",
    )

    joined = 0
    failed = 0
    for s in targets:
        try:
            link = f"@{s.username}" if s.username else s.invite_link
            ok = await join_channel_link(telethon_client, link)
            if ok:
                joined += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(1.5)

    # Reset cursors so the next poll picks up recent posts from newly joined channels
    reset_last_seen()

    text = (
        f"✅ Готово!\n• Вступил/уже состоит: <b>{joined}</b>\n• Ошибок: <b>{failed}</b>\n"
        f"• Пропущено (уже были в диалогах): <b>{already_known}</b>\n\n"
        f"Курсоры сброшены — посты пойдут в течение ~1 минуты."
    )
    if no_link:
        names = ", ".join((s.title or str(s.telegram_id)) for s in no_link[:15])
        more = f" и ещё {len(no_link) - 15}" if len(no_link) > 15 else ""
        text += (
            f"\n\n⚠️ <b>{len(no_link)}</b> источников без username и без сохранённой "
            f"инвайт-ссылки — вступить в них невозможно (ссылка была утеряна до этого "
            f"фикса): {names}{more}"
        )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("addquick"))
async def cmd_addquick(message: Message) -> None:
    """One-shot setup: join source, add source+dest, create route,
    enable strip_footer, reset cursor.
    Usage: /addquick <source_link> <dest_id_or_link> [nofooter]
    Example: /addquick https://t.me/gdebenzkzn -1004489362200
             /addquick https://t.me/gdebenzkzn -1004489362200 nofooter
    (footer stripping is ON by default; pass "nofooter" to skip it)"""
    from app.telethon_client.client import telethon_client
    from app.services.channel_service import (
        join_channel_link, add_source_channel, add_destination_channel, create_route,
    )

    parts = message.text.split() if message.text else []
    if len(parts) < 3:
        await message.answer(
            "Использование:\n<code>/addquick ссылка_источник ID_или_ссылка_назначение [nofooter]</code>\n\n"
            "Пример:\n<code>/addquick https://t.me/gdebenzkzn -1004489362200</code>",
            parse_mode="HTML",
        )
        return

    source_link = parts[1]
    dest_link = parts[2]
    strip_footer = "nofooter" not in [p.lower() for p in parts[3:]]

    client = telethon_client
    steps = []

    joined = await join_channel_link(client, source_link)
    steps.append(f"{'✅' if joined else '⚠️'} Вступление в источник")

    try:
        async with async_session_factory() as session:
            src, src_created = await add_source_channel(session, client, source_link)
            dst, dst_created = await add_destination_channel(session, client, dest_link)
            route, route_created = await create_route(session, src.id, dst.id)
            if strip_footer and not route.strip_footer:
                route.strip_footer = True
            await session.commit()
            route_id = route.id
            final_strip_footer = route.strip_footer
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\n\n" + "\n".join(steps))
        return

    steps.append(f"✅ Источник: {'добавлен' if src_created else 'уже был'} (id={src.id})")
    steps.append(f"✅ Назначение: {'добавлено' if dst_created else 'уже было'} (id={dst.id})")
    steps.append(f"✅ Маршрут: {'создан' if route_created else 'уже существовал'} (#{route_id})")
    steps.append(f"{'✅' if final_strip_footer else '☑️'} Авто-удаление плашки: {'включено' if final_strip_footer else 'выключено'}")

    reset_last_seen([src.telegram_id])
    steps.append("🔄 Курсор сброшен — посты пойдут в течение ~1 минуты")

    await message.answer("<b>Готово!</b>\n\n" + "\n".join(steps), parse_mode="HTML")


@router.message(Command("renamedest"))
async def cmd_renamedest(message: Message) -> None:
    """Rename a destination channel's display title in the DB.
    Usage: /renamedest <telegram_id> <новое название>
    Example: /renamedest -1004348793477 Парсер Башкортостан"""
    from sqlalchemy import select
    from app.models.channel import DestinationChannel

    parts = message.text.split(maxsplit=2) if message.text else []
    if len(parts) < 3:
        await message.answer(
            "Использование:\n<code>/renamedest ID новое_название</code>\n\n"
            "Пример:\n<code>/renamedest -1004348793477 Парсер Башкортостан</code>",
            parse_mode="HTML",
        )
        return

    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ ID канала должен быть числом (например -1004348793477).")
        return

    new_title = parts[2].strip()

    async with async_session_factory() as session:
        result = await session.execute(
            select(DestinationChannel).where(DestinationChannel.telegram_id == telegram_id)
        )
        dest = result.scalar_one_or_none()
        if dest is None:
            await message.answer(f"❌ Назначение с ID <code>{telegram_id}</code> не найдено.", parse_mode="HTML")
            return
        old_title = dest.title
        dest.title = new_title
        await session.commit()

    await message.answer(
        f"✅ Переименовано!\n\n<code>{telegram_id}</code>\n«{old_title or '(без названия)'}» → «{new_title}»",
        parse_mode="HTML",
    )


# ── FREE-TEXT CHANNEL SEARCH ──────────────────────────────────────────────────
# Typing plain text (not a command, no active FSM step) searches sources and
# destinations by name/username substring, so you don't need /debugsource.

@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def search_channels_by_text(message: Message) -> None:
    query = message.text.strip().lower().lstrip("@")
    if len(query) < 2:
        return

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()
        dests = await repo.list_all_destinations()

    src_matches = [s for s in sources if query in (s.username or "").lower() or query in (s.title or "").lower()]
    dst_matches = [d for d in dests if query in (d.username or "").lower() or query in (d.title or "").lower()]

    if not src_matches and not dst_matches:
        return  # not a channel search — avoid noisy replies to unrelated chat

    lines = [f"🔎 <b>Найдено по «{message.text.strip()}»:</b>\n"]
    if src_matches:
        lines.append("📥 <b>Источники:</b>")
        for s in src_matches[:15]:
            status = "✅" if s.is_active else "⏸"
            lines.append(f"{status} {channel_display_name(s)} — <code>{s.telegram_id}</code>")
    if dst_matches:
        lines.append("\n📤 <b>Назначения:</b>")
        for d in dst_matches[:15]:
            status = "✅" if d.is_active else "⏸"
            lines.append(f"{status} {channel_display_name(d)} — <code>{d.telegram_id}</code>")

    await message.answer("\n".join(lines), parse_mode="HTML")
