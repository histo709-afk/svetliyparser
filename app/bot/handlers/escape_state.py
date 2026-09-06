"""Let a command always break out of a half-finished wizard.

Every FSM step in this bot is registered as a bare state filter (e.g.
`@router.message(AddSourceStates.waiting_link)`) with no condition on the
text, so while a wizard is open it swallows *every* message — including
commands. A user who starts "Добавить источник", wanders off, and later
sends `/addquick ...` gets their command eaten by the wizard, which then
tries to resolve the whole command line as a channel link and answers
"🔍 Ищу канал..." — looking exactly like the bot hung.

This router is registered first, so it sees commands before any wizard
does: it clears the stale state and then re-raises SkipHandler, letting
the real command handler further down run as if no wizard had been open.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router(name="escape_state")


@router.message(StateFilter("*"), F.text.startswith("/"))
async def release_state_for_command(message: Message, state: FSMContext) -> None:
    if await state.get_state() is not None:
        await state.clear()
    raise SkipHandler
