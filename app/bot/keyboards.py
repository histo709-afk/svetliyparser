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


def source_selection_keyboard(sources: List[SourceChannel]) -> InlineKeyboardMarkup:
    """Keyboard for selecting a source channel."""
    builder = InlineKeyboardBuilder()
    for src in sources:
        builder.row(
            InlineKeyboardButton(
                text=channel_display_name(src),
                callback_data=f"select_source:{src.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
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
