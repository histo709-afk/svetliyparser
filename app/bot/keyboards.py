"""Inline keyboards for the management bot."""
from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models.channel import SourceChannel
from app.services.channel_service import channel_display_name


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


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()
