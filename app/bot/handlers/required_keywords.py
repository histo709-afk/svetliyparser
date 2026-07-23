"""Required-keywords management: a route with configured keywords only
forwards posts containing at least one of them."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import async_session_factory
from app.repositories.required_keyword_repo import RequiredKeywordRepository
from app.repositories.route_repo import RouteRepository

router = Router(name="required_keywords")


class RequiredKeywordStates(StatesGroup):
    adding = State()


async def _try_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def _edit_prompt(bot, chat_id: int, msg_id: int, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass


async def _show_route_keywords(message: Message, route_id: int, edit: bool = False) -> None:
    async with async_session_factory() as session:
        kw_repo = RequiredKeywordRepository(session)
        rt_repo = RouteRepository(session)
        words = await kw_repo.list_for_route(route_id)
        route = await rt_repo.get_route_by_id(route_id)

    src = route.source.title or route.source.username or f"src#{route.source_id}" if route and route.source else "?"
    dst = route.destination.title or route.destination.username or f"dst#{route.destination_id}" if route and route.destination else "?"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить слова", callback_data=f"rk_add:{route_id}"))
    for w in words:
        builder.row(InlineKeyboardButton(text=f"❌ {w.word}", callback_data=f"rk_del:{w.id}:{route_id}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"route_info:{route_id}:0:active"))

    if words:
        text = (
            f"🔑 <b>Обязательные слова для маршрута:</b>\n{src} → {dst}\n\n"
            f"Пост пересылается, только если содержит хотя бы одно из {len(words)} слов ниже."
        )
    else:
        text = (
            f"🔑 <b>Обязательные слова для маршрута:</b>\n{src} → {dst}\n\n"
            f"Список пуст — фильтр не действует, пересылаются все посты (кроме отфильтрованных другими правилами)."
        )

    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("rk_select_route:"))
async def cb_rk_select_route(callback: CallbackQuery, state: FSMContext) -> None:
    route_id = int(callback.data.split(":")[1])
    await state.clear()
    await _show_route_keywords(callback.message, route_id, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("rk_add:"))
async def cb_rk_add(callback: CallbackQuery, state: FSMContext) -> None:
    route_id = int(callback.data.split(":")[1])
    await state.update_data(route_id=route_id,
                            prompt_msg_id=callback.message.message_id,
                            prompt_chat_id=callback.message.chat.id)
    await state.set_state(RequiredKeywordStates.adding)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"rk_select_route:{route_id}"))
    await callback.message.edit_text(
        "🔑 <b>Обязательные слова</b>\n\n"
        "Отправьте слова/фразы через запятую или каждое с новой строки. "
        "Пост будет пересылаться, только если содержит <b>хотя бы одно</b> из них:\n\n"
        "<i>Пример: #татнефть, #тебойл, дт, 92, 95, очередь</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RequiredKeywordStates.adding)
async def process_add_keywords(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    route_id = data.get("route_id")
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id")

    await _try_delete(message)

    if not route_id:
        return

    text = message.text or ""
    raw_words = [w.strip() for w in text.replace("\n", ",").split(",") if w.strip()]
    if not raw_words:
        if prompt_msg_id:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"rk_select_route:{route_id}"))
            await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                               "⚠️ Нет слов. Попробуйте ещё раз:", builder.as_markup())
        return

    added = 0
    skipped = 0
    async with async_session_factory() as session:
        repo = RequiredKeywordRepository(session)
        for w in raw_words:
            result = await repo.add(w, route_id=route_id)
            if result:
                added += 1
            else:
                skipped += 1
        await session.commit()

    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К маршруту", callback_data=f"rk_select_route:{route_id}"))
    result_text = f"✅ Добавлено: <b>{added}</b>\n⏭ Уже было: <b>{skipped}</b>"

    if prompt_msg_id:
        await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id, result_text, builder.as_markup())
    else:
        await message.answer(result_text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("rk_del:"))
async def cb_rk_delete(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    kw_id = int(parts[1])
    route_id = int(parts[2])

    async with async_session_factory() as session:
        repo = RequiredKeywordRepository(session)
        await repo.delete_by_id(kw_id)
        await session.commit()

    await callback.answer("✅ Удалено")
    await _show_route_keywords(callback.message, route_id, edit=True)
