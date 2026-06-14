"""Start command and main menu."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from app.bot.keyboards import main_menu_keyboard

router = Router(name="start")

WELCOME_TEXT = "👋 <b>Светлый Парсер</b>"

# FSM key to store the bot's main menu message_id
MENU_MSG_KEY = "main_menu_msg_id"


def _persistent_keyboard() -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Меню"))
    return builder.as_markup(resize_keyboard=True)


async def _show_main_menu(message: Message, state: FSMContext) -> None:
    """Delete user message, then edit existing menu message or send a new one."""
    data = await state.get_data()
    menu_msg_id = data.get(MENU_MSG_KEY)

    # Try to delete the user's "Меню" message
    try:
        await message.delete()
    except Exception:
        pass

    # Try to edit the existing menu message
    if menu_msg_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=menu_msg_id,
                text=WELCOME_TEXT,
                reply_markup=main_menu_keyboard(),
                parse_mode="HTML",
            )
            return
        except Exception:
            pass

    # Send new menu message and save its id
    sent = await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    await state.update_data({MENU_MSG_KEY: sent.message_id})


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    # Send persistent reply keyboard once
    await message.answer(".", reply_markup=_persistent_keyboard())
    sent = await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    await state.update_data({MENU_MSG_KEY: sent.message_id})


@router.message(F.text == "Меню")
async def btn_menu(message: Message, state: FSMContext) -> None:
    await _show_main_menu(message, state)


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        WELCOME_TEXT, reply_markup=main_menu_keyboard(), parse_mode="HTML"
    )
    await state.update_data({MENU_MSG_KEY: callback.message.message_id})
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()
