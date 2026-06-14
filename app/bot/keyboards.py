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
    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"src_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"src_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def routes_list_keyboard(routes: list, page: int = 0) -> InlineKeyboardMarkup:
    """Paginated routes list with delete button per route (10 per page)."""
    PAGE_SIZE = 10
    total = len(routes)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_routes = routes[start:end]

    builder = InlineKeyboardBuilder()
    for r in page_routes:
        src_name = (channel_display_name(r.source) if r.source else f"src#{r.source_id}")[:25]
        dst_name = (channel_display_name(r.destination) if r.destination else f"dst#{r.destination_id}")[:25]
        status_icon = "✅" if r.is_active else "⏸"
        label = f"{status_icon} {src_name} → {dst_name}"
        builder.row(
            InlineKeyboardButton(text=label[:60], callback_data=f"route_info:{r.id}:{page}"),
            InlineKeyboardButton(text="🗑", callback_data=f"delete_route:{r.id}:{page}"),
        )

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"routes_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"routes_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def route_actions_keyboard(route_id: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить маршрут", callback_data=f"confirm_delete_route:{route_id}:{page}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад к списку", callback_data=f"routes_page:{page}"),
    )
    return builder.as_markup()


def confirm_delete_keyboard(route_id: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"do_delete_route:{route_id}:{page}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"routes_page:{page}"),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()
