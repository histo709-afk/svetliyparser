"""Text replacement rules management handler."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import async_session_factory
from app.repositories.text_replacement_repo import TextReplacementRepository
from app.repositories.route_repo import RouteRepository

router = Router(name="text_replacements")


class TRStates(StatesGroup):
    waiting_find = State()
    waiting_replace = State()


async def _try_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def _edit_prompt(bot, chat_id: int, msg_id: int, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=markup, parse_mode="HTML",
        )
    except Exception:
        pass


def _tr_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌍 Глобальные замены", callback_data="tr_global"))
    builder.row(InlineKeyboardButton(text="🎯 Для маршрута", callback_data="tr_per_route"))
    builder.row(InlineKeyboardButton(text="📋 Все правила", callback_data="tr_list:0"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _back_to_tr_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="text_replacements"))
    return builder.as_markup()


@router.callback_query(F.data == "text_replacements")
async def cb_tr_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "✂️ <b>Замена текста</b>\n\nПравила для удаления или замены фраз в постах перед пересылкой:",
        reply_markup=_tr_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── GLOBAL ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tr_global")
async def cb_tr_global(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        rules = await repo.list_global()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить правило", callback_data="tr_add:global"))
    for r in rules:
        preview = r.find_text[:25] + ("…" if len(r.find_text) > 25 else "")
        replace_preview = f" → «{r.replace_with[:15]}»" if r.replace_with else " → (удалить)"
        builder.row(InlineKeyboardButton(
            text=f"❌ «{preview}»{replace_preview}",
            callback_data=f"tr_del:{r.id}:global",
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="text_replacements"))

    await callback.message.edit_text(
        f"🌍 <b>Глобальные замены</b> ({len(rules)}):\n\nПрименяются ко всем маршрутам.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── PER-ROUTE ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tr_per_route")
async def cb_tr_per_route(callback: CallbackQuery, state: FSMContext) -> None:
    await _show_route_selection(callback.message, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith("tr_route_page:"))
async def cb_tr_route_page(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    await _show_route_selection(callback.message, page=page)
    await callback.answer()


async def _show_route_selection(message: Message, page: int) -> None:
    PAGE_SIZE = 10
    async with async_session_factory() as session:
        repo = RouteRepository(session)
        routes = await repo.list_all_routes()

    total = len(routes)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    builder = InlineKeyboardBuilder()
    for r in routes[start:end]:
        src = r.source.title or r.source.username or f"src#{r.source_id}" if r.source else f"src#{r.source_id}"
        dst = r.destination.title or r.destination.username or f"dst#{r.destination_id}" if r.destination else f"dst#{r.destination_id}"
        builder.row(InlineKeyboardButton(
            text=f"{src[:20]} → {dst[:20]}",
            callback_data=f"tr_select_route:{r.id}",
        ))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tr_route_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tr_route_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="text_replacements"))

    await message.edit_text(
        f"🎯 <b>Замены для маршрута</b>\n\nВыберите маршрут ({total} всего):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("tr_select_route:"))
async def cb_tr_select_route(callback: CallbackQuery) -> None:
    route_id = int(callback.data.split(":")[1])
    await _show_route_rules(callback.message, route_id)
    await callback.answer()


async def _show_route_rules(message: Message, route_id: int) -> None:
    async with async_session_factory() as session:
        tr_repo = TextReplacementRepository(session)
        rt_repo = RouteRepository(session)
        rules = await tr_repo.list_for_route(route_id)
        route = await rt_repo.get_route_by_id(route_id)

    src = route.source.title or route.source.username or f"src#{route.source_id}" if route and route.source else "?"
    dst = route.destination.title or route.destination.username or f"dst#{route.destination_id}" if route and route.destination else "?"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить правило", callback_data=f"tr_add:route:{route_id}"))
    for r in rules:
        preview = r.find_text[:25] + ("…" if len(r.find_text) > 25 else "")
        replace_preview = f" → «{r.replace_with[:15]}»" if r.replace_with else " → (удалить)"
        builder.row(InlineKeyboardButton(
            text=f"❌ «{preview}»{replace_preview}",
            callback_data=f"tr_del:{r.id}:route:{route_id}",
        ))
    builder.row(InlineKeyboardButton(text="◀️ К маршрутам", callback_data="tr_per_route"))

    await message.edit_text(
        f"🎯 <b>Замены для маршрута:</b>\n{src} → {dst}\n\nПравил: <b>{len(rules)}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ── ADD RULE ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tr_add:"))
async def cb_tr_add(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    # tr_add:global  or  tr_add:route:123
    if parts[1] == "global":
        await state.update_data(tr_route_id=None, tr_back="tr_global",
                                prompt_msg_id=callback.message.message_id,
                                prompt_chat_id=callback.message.chat.id)
    else:
        route_id = int(parts[2])
        await state.update_data(tr_route_id=route_id, tr_back=f"tr_select_route:{route_id}",
                                prompt_msg_id=callback.message.message_id,
                                prompt_chat_id=callback.message.chat.id)

    await state.set_state(TRStates.waiting_find)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=callback.data.replace("tr_add:", "tr_add_cancel:")))

    await callback.message.edit_text(
        "✂️ <b>Новое правило замены</b>\n\n"
        "Шаг 1 из 2: Отправьте <b>текст который нужно найти</b> в посте:\n\n"
        "<i>Например: Встречаемся в МАКС (https://max.ru)</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TRStates.waiting_find)
async def process_find_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id")

    await _try_delete(message)

    find_text = (message.text or "").strip()
    if not find_text:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="text_replacements"))
        await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                           "⚠️ Пустой текст. Отправьте фразу для поиска:", builder.as_markup())
        return

    await state.update_data(tr_find_text=find_text)
    await state.set_state(TRStates.waiting_replace)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑 Просто удалить", callback_data="tr_replace_empty"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="text_replacements"))

    await _edit_prompt(
        message.bot, prompt_chat_id, prompt_msg_id,
        f"✂️ <b>Новое правило замены</b>\n\n"
        f"Найти: <code>{find_text[:100]}</code>\n\n"
        f"Шаг 2 из 2: Отправьте <b>текст для замены</b>\n"
        f"Или нажмите «Просто удалить» чтобы убрать фразу:",
        builder.as_markup(),
    )


@router.callback_query(F.data == "tr_replace_empty")
async def cb_tr_replace_empty(callback: CallbackQuery, state: FSMContext) -> None:
    await _save_rule(callback, state, replace_with="")


@router.message(TRStates.waiting_replace)
async def process_replace_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await _try_delete(message)
    replace_with = (message.text or "").strip()
    await _save_rule_from_message(message, state, replace_with)


async def _save_rule(callback: CallbackQuery, state: FSMContext, replace_with: str) -> None:
    data = await state.get_data()
    find_text = data.get("tr_find_text", "")
    route_id = data.get("tr_route_id")
    back = data.get("tr_back", "text_replacements")
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id") or callback.message.chat.id

    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        result = await repo.add(find_text, replace_with, route_id=route_id)
        await session.commit()

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=back))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    if result is None:
        text = "ℹ️ Такое правило уже существует."
    else:
        action = "удалить" if not replace_with else f"заменить на «{replace_with[:50]}»"
        text = f"✅ <b>Правило добавлено!</b>\n\nНайти: <code>{find_text[:100]}</code>\nДействие: {action}"

    await _edit_prompt(callback.bot, prompt_chat_id, prompt_msg_id, text, builder.as_markup())
    await callback.answer()


async def _save_rule_from_message(message: Message, state: FSMContext, replace_with: str) -> None:
    data = await state.get_data()
    find_text = data.get("tr_find_text", "")
    route_id = data.get("tr_route_id")
    back = data.get("tr_back", "text_replacements")
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id") or message.chat.id

    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        result = await repo.add(find_text, replace_with, route_id=route_id)
        await session.commit()

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=back))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))

    if result is None:
        text = "ℹ️ Такое правило уже существует."
    else:
        action = "удалить" if not replace_with else f"заменить на «{replace_with[:50]}»"
        text = f"✅ <b>Правило добавлено!</b>\n\nНайти: <code>{find_text[:100]}</code>\nДействие: {action}"

    await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id, text, builder.as_markup())


# ── LIST ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tr_list:"))
async def cb_tr_list(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[1])
    PAGE_SIZE = 10

    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        rt_repo = RouteRepository(session)
        rules = await repo.list_all()
        route_names: dict[int, str] = {}
        for r in rules:
            if r.route_id and r.route_id not in route_names:
                route = await rt_repo.get_route_by_id(r.route_id)
                if route:
                    src = route.source.title or route.source.username or f"#{route.source_id}" if route.source else f"#{route.source_id}"
                    dst = route.destination.title or route.destination.username or f"#{route.destination_id}" if route.destination else f"#{route.destination_id}"
                    route_names[r.route_id] = f"{src[:12]}→{dst[:12]}"

    total = len(rules)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    lines = []
    for r in rules[start:end]:
        scope = "🌍" if r.route_id is None else f"🎯{route_names.get(r.route_id, f'#{r.route_id}')}"
        find_p = r.find_text[:30] + ("…" if len(r.find_text) > 30 else "")
        replace_p = f" → «{r.replace_with[:20]}»" if r.replace_with else " → (удалить)"
        lines.append(f"• {scope} <code>{find_p}</code>{replace_p}")

    text = f"📋 <b>Все правила замены</b> ({total}):\n\n" + ("\n".join(lines) if lines else "Список пуст")

    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"tr_list:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"tr_list:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="text_replacements"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("tr_del:"))
async def cb_tr_delete(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    tr_id = int(parts[1])
    back = parts[2] if len(parts) > 2 else "global"

    async with async_session_factory() as session:
        repo = TextReplacementRepository(session)
        await repo.delete_by_id(tr_id)
        await session.commit()

    await callback.answer("✅ Удалено")

    if back == "global":
        await cb_tr_global(callback, None)
    elif back == "route" and len(parts) > 3:
        route_id = int(parts[3])
        await _show_route_rules(callback.message, route_id)
    else:
        await cb_tr_global(callback, None)
