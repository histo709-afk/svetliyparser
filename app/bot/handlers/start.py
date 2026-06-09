"""Start command and main menu."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import main_menu_keyboard

router = Router(name="start")

WELCOME_TEXT = (
    "👋 <b>Светлый Парсер</b>\n\n"
    "Бот для автоматической пересылки сообщений между Telegram-каналами.\n\n"
    "Выберите действие:"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "❌ Действие отменено.\n\n" + WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
