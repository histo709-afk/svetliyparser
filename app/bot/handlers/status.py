"""Status, routes, and log handlers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import (
    back_to_menu_keyboard,
    confirm_delete_route_keyboard,
    route_actions_keyboard,
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
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, getattr(route, "strip_footer", False)),
        parse_mode="HTML",
    )
    await callback.answer()


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
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, getattr(route, "strip_footer", False)),
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
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, getattr(route, "strip_footer", False)),
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
        reply_markup=route_actions_keyboard(route_id, page, filter_, route.is_active, route.strip_footer),
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


@router.message(Command("getids"))
async def cmd_getids(message: Message) -> None:
    """Lookup telegram_ids for channels by username.
    Usage: /getids username1 username2 ...
    Also searches destination channels."""
    parts = message.text.split() if message.text else []
    if len(parts) < 2:
        await message.answer("Использование: /getids username1 username2 ...\nПример: /getids chelny almet_light lightkazan")
        return

    usernames = [p.lstrip("@").lower() for p in parts[1:]]

    async with async_session_factory() as session:
        repo = ChannelRepository(session)
        sources = await repo.list_all_sources()
        dests = await repo.list_all_destinations()

    all_channels = [(s.username, s.title, s.telegram_id, "src") for s in sources] + \
                   [(d.username, d.title, d.telegram_id, "dst") for d in dests]

    lines = []
    not_found = []
    for uname in usernames:
        match = next((c for c in all_channels if (c[0] or "").lower() == uname), None)
        if match:
            lines.append(f"<b>{match[1] or match[0]}</b>\n@{match[0]}\n<code>{match[2]}</code>")
        else:
            not_found.append(uname)

    if lines:
        await message.answer("\n\n".join(lines), parse_mode="HTML")
    if not_found:
        await message.answer(f"Не найдены в БД: {', '.join(not_found)}")
