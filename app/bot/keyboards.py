"""Inline keyboards for the management bot."""
from __future__ import annotations

from typing import List, TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.channel import SourceChannel
from app.services.channel_service import channel_display_name

if TYPE_CHECKING:
    from app.models.route import Route


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Добавить источник", callback_data="add_source"),
        InlineKeyboardButton(text="➕ Добавить назначение", callback_data="add_dest"),
    )
    builder.row(
        InlineKeyboardButton(text="🔀 Маршруты", callback_data="routes"),
        InlineKeyboardButton(text="📊 Статус", callback_data="status"),
    )
    builder.row(
        InlineKeyboardButton(text="⚠️ Последние ошибки", callback_data="logs"),
    )
    builder.row(
        InlineKeyboardButton(text="🚫 Запретные слова", callback_data="banned_words"),
    )
    return builder.as_markup()


def routes_filter_keyboard() -> InlineKeyboardMarkup:
    """Submenu: choose active or stopped routes."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="▶️ Запущенные", callback_data="routes_filter:active:0"),
        InlineKeyboardButton(text="⏸ Остановленные", callback_data="routes_filter:stopped:0"),
    )
    builder.row(InlineKeyboardButton(text="🗄 Архив", callback_data="routes_archive"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def routes_list_keyboard(routes: list, page: int = 0, filter_: str = "active") -> InlineKeyboardMarkup:
    """Paginated routes list (10 per page). Each row = one route."""
    PAGE_SIZE = 10
    total = len(routes)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    builder = InlineKeyboardBuilder()
    for r in routes[start:end]:
        src_name = (channel_display_name(r.source) if r.source else f"src#{r.source_id}")[:25]
        dst_name = (channel_display_name(r.destination) if r.destination else f"dst#{r.destination_id}")[:25]
        status_icon = "✅" if r.is_active else "⏸"
        label = f"{status_icon} {src_name} → {dst_name}"
        builder.row(
            InlineKeyboardButton(
                text=label[:60],
                callback_data=f"route_info:{r.id}:{page}:{filter_}",
            )
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"routes_filter:{filter_}:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"routes_filter:{filter_}:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="routes"))
    return builder.as_markup()


def route_actions_keyboard(route_id: int, page: int, filter_: str, is_active: bool) -> InlineKeyboardMarkup:
    """Per-route settings menu."""
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.row(InlineKeyboardButton(text="⏸ Остановить маршрут", callback_data=f"route_stop:{route_id}:{page}:{filter_}"))
    else:
        builder.row(InlineKeyboardButton(text="▶️ Запустить маршрут", callback_data=f"route_start:{route_id}:{page}:{filter_}"))
    builder.row(InlineKeyboardButton(text="🚫 Запретные слова", callback_data=f"bw_select_route:{route_id}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить маршрут", callback_data=f"delete_route:{route_id}:{page}:{filter_}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"routes_filter:{filter_}:{page}"))
    return builder.as_markup()


def confirm_delete_route_keyboard(route_id: int, page: int, filter_: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"do_delete_route:{route_id}:{page}:{filter_}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"route_info:{route_id}:{page}:{filter_}"),
    )
    return builder.as_markup()


# Keep old name as alias for any legacy code
def confirm_delete_keyboard(route_id: int, page: int = 0) -> InlineKeyboardMarkup:
    return confirm_delete_route_keyboard(route_id, page, "active")


def source_selection_keyboard(sources: List[SourceChannel], page: int = 0) -> InlineKeyboardMarkup:
    """Keyboard for selecting a source channel (paginated, 30 per page)."""
    PAGE_SIZE = 30
    total = len(sources)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_sources = sources[start:end]

    builder = InlineKeyboardBuilder()
    for src in page_sources:
        builder.row(
            InlineKeyboardButton(
                text=channel_display_name(src)[:40],
                callback_data=f"select_source:{src.id}",
            )
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"src_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"src_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()
