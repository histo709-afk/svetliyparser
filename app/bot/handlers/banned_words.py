"""Banned words management handler."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import async_session_factory
from app.repositories.banned_word_repo import BannedWordRepository
from app.repositories.route_repo import RouteRepository

router = Router(name="banned_words")


class BannedWordsStates(StatesGroup):
    adding_global = State()
    selecting_route = State()
    adding_route_words = State()
    adding_route_exception = State()
    searching = State()


def _banned_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🌍 Глобальные слова", callback_data="bw_global"))
    builder.row(InlineKeyboardButton(text="🎯 Индивидуальный запрет", callback_data="bw_per_route"))
    builder.row(InlineKeyboardButton(text="📋 Все запретные слова", callback_data="bw_list:0"))
    builder.row(InlineKeyboardButton(text="🔍 Поиск слова", callback_data="bw_search"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    return builder.as_markup()


def _back_to_banned_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="banned_words"))
    return builder.as_markup()


async def _try_delete(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def _edit_prompt(bot, chat_id: int, msg_id: int, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "banned_words")
async def cb_banned_words_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "🚫 <b>Запретные слова</b>\n\nВыберите тип фильтра:",
        reply_markup=_banned_menu_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── GLOBAL WORDS ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "bw_global")
async def cb_bw_global(callback: CallbackQuery, state: FSMContext) -> None:
    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        words = await repo.list_global()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить слова", callback_data="bw_add_global"))
    for w in words:
        builder.row(InlineKeyboardButton(
            text=f"❌ {w.word}", callback_data=f"bw_del:{w.id}:global"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="banned_words"))

    count = len(words)
    text = f"🌍 <b>Глобальные запретные слова</b> ({count}):\n\nПосты содержащие эти слова не будут пересылаться ни в один канал."
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "bw_add_global")
async def cb_bw_add_global(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BannedWordsStates.adding_global)
    await state.update_data(prompt_msg_id=callback.message.message_id,
                            prompt_chat_id=callback.message.chat.id)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="bw_global"))
    await callback.message.edit_text(
        "🌍 <b>Добавление глобальных запретных слов</b>\n\n"
        "Отправьте слова через запятую или каждое с новой строки:\n\n"
        "<i>Пример: реклама, скидка, акция</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BannedWordsStates.adding_global)
async def process_add_global(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id")

    await _try_delete(message)

    text = message.text or ""
    raw_words = [w.strip() for w in text.replace("\n", ",").split(",") if w.strip()]

    if not raw_words:
        if prompt_msg_id:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="bw_global"))
            await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                               "⚠️ Нет слов. Попробуйте ещё раз:", builder.as_markup())
        return

    added = 0
    skipped = 0
    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        for w in raw_words:
            result = await repo.add(w, route_id=None)
            if result:
                added += 1
            else:
                skipped += 1
        await session.commit()

    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К глобальным словам", callback_data="bw_global"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    result_text = f"✅ Добавлено: <b>{added}</b>\n⏭ Уже было: <b>{skipped}</b>"

    if prompt_msg_id:
        await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                           result_text, builder.as_markup())
    else:
        await message.answer(result_text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ── PER-ROUTE WORDS ───────────────────────────────────────────────────────────

@router.callback_query(F.data == "bw_per_route")
async def cb_bw_per_route(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BannedWordsStates.selecting_route)
    await _show_route_selection(callback.message, page=0, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("bw_route_page:"))
async def cb_bw_route_page(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    await _show_route_selection(callback.message, page=page, edit=True)
    await callback.answer()


async def _show_route_selection(message: Message, page: int, edit: bool = False) -> None:
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
        label = f"{src[:20]} → {dst[:20]}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"bw_select_route:{r.id}"))

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"bw_route_page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"bw_route_page:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="banned_words"))

    text = f"🎯 <b>Индивидуальный запрет</b>\n\nВыберите маршрут ({total} всего):"
    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("bw_select_route:"))
async def cb_bw_select_route(callback: CallbackQuery, state: FSMContext) -> None:
    route_id = int(callback.data.split(":")[1])
    await state.update_data(route_id=route_id)
    await _show_route_words(callback.message, route_id, edit=True)
    await state.set_state(BannedWordsStates.adding_route_words)
    await callback.answer()


async def _show_route_words(message: Message, route_id: int, edit: bool = False) -> None:
    async with async_session_factory() as session:
        bw_repo = BannedWordRepository(session)
        rt_repo = RouteRepository(session)
        words = await bw_repo.list_for_route(route_id)
        route = await rt_repo.get_route_by_id(route_id)

    src = route.source.title or route.source.username or f"src#{route.source_id}" if route and route.source else "?"
    dst = route.destination.title or route.destination.username or f"dst#{route.destination_id}" if route and route.destination else "?"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить слова", callback_data=f"bw_add_route:{route_id}"))
    builder.row(InlineKeyboardButton(text="🟢 Исключение (разрешить глобальное слово)", callback_data=f"bw_add_exception:{route_id}"))
    for w in words:
        icon = "🟢" if w.is_exception else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{icon} {w.word}", callback_data=f"bw_del:{w.id}:route:{route_id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ К маршрутам", callback_data="bw_per_route"))

    text = (
        f"🎯 <b>Запрет для маршрута:</b>\n{src} → {dst}\n\n"
        f"Слов: <b>{len(words)}</b>\n\n"
        f"🟢 — исключение: слово запрещено глобально, но <b>разрешено</b> для этого маршрута"
    )
    if edit:
        await message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("bw_add_route:"))
async def cb_bw_add_route(callback: CallbackQuery, state: FSMContext) -> None:
    route_id = int(callback.data.split(":")[1])
    await state.update_data(route_id=route_id,
                            prompt_msg_id=callback.message.message_id,
                            prompt_chat_id=callback.message.chat.id)
    await state.set_state(BannedWordsStates.adding_route_words)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"bw_select_route:{route_id}"))
    await callback.message.edit_text(
        "🎯 <b>Добавление запретных слов для маршрута</b>\n\n"
        "Отправьте слова через запятую или каждое с новой строки:\n\n"
        "<i>Пример: реклама, скидка, акция</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BannedWordsStates.adding_route_words)
async def process_add_route_words(message: Message, state: FSMContext) -> None:
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
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"bw_select_route:{route_id}"))
            await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                               "⚠️ Нет слов. Попробуйте ещё раз:", builder.as_markup())
        return

    added = 0
    skipped = 0
    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        for w in raw_words:
            result = await repo.add(w, route_id=route_id)
            if result:
                added += 1
            else:
                skipped += 1
        await session.commit()

    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К маршруту", callback_data=f"bw_select_route:{route_id}"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    result_text = f"✅ Добавлено: <b>{added}</b>\n⏭ Уже было: <b>{skipped}</b>"

    if prompt_msg_id:
        await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                           result_text, builder.as_markup())
    else:
        await message.answer(result_text, reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("bw_add_exception:"))
async def cb_bw_add_exception(callback: CallbackQuery, state: FSMContext) -> None:
    route_id = int(callback.data.split(":")[1])
    await state.update_data(route_id=route_id,
                            prompt_msg_id=callback.message.message_id,
                            prompt_chat_id=callback.message.chat.id)
    await state.set_state(BannedWordsStates.adding_route_exception)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"bw_select_route:{route_id}"))
    await callback.message.edit_text(
        "🟢 <b>Исключение для маршрута</b>\n\n"
        "Отправьте слово(а), которые запрещены глобально, но должны "
        "<b>пропускаться</b> именно для этого маршрута:\n\n"
        "<i>Пример: реклама</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BannedWordsStates.adding_route_exception)
async def process_add_route_exception(message: Message, state: FSMContext) -> None:
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
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"bw_select_route:{route_id}"))
            await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                               "⚠️ Нет слов. Попробуйте ещё раз:", builder.as_markup())
        return

    added = 0
    skipped = 0
    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        for w in raw_words:
            result = await repo.add(w, route_id=route_id, is_exception=True)
            if result:
                added += 1
            else:
                skipped += 1
        await session.commit()

    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К маршруту", callback_data=f"bw_select_route:{route_id}"))
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"))
    result_text = f"✅ Добавлено исключений: <b>{added}</b>\n⏭ Уже было: <b>{skipped}</b>"

    if prompt_msg_id:
        await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                           result_text, builder.as_markup())
    else:
        await message.answer(result_text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ── FULL LIST ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("bw_list:"))
async def cb_bw_list(callback: CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split(":")[1])
    PAGE_SIZE = 15

    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        rt_repo = RouteRepository(session)
        words = await repo.list_all()
        route_names: dict[int, str] = {}
        for w in words:
            if w.route_id and w.route_id not in route_names:
                r = await rt_repo.get_route_by_id(w.route_id)
                if r:
                    src = r.source.title or r.source.username or f"#{r.source_id}" if r.source else f"#{r.source_id}"
                    dst = r.destination.title or r.destination.username or f"#{r.destination_id}" if r.destination else f"#{r.destination_id}"
                    route_names[w.route_id] = f"{src[:15]}→{dst[:15]}"

    total = len(words)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    lines = []
    for w in words[start:end]:
        scope = "🌍" if w.route_id is None else f"🎯{route_names.get(w.route_id, f'#{w.route_id}')}"
        exc = " (исключение)" if w.is_exception else ""
        lines.append(f"• {scope} <code>{w.word}</code>{exc}")

    text = f"📋 <b>Все запретные слова</b> ({total}):\n\n" + ("\n".join(lines) if lines else "Список пуст")

    builder = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"bw_list:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"bw_list:{page+1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="banned_words"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ── SEARCH ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "bw_search")
async def cb_bw_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BannedWordsStates.searching)
    await state.update_data(prompt_msg_id=callback.message.message_id,
                            prompt_chat_id=callback.message.chat.id)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="banned_words"))
    await callback.message.edit_text(
        "🔍 <b>Поиск запретного слова</b>\n\nНапишите слово для поиска:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BannedWordsStates.searching)
async def process_search(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    prompt_chat_id = data.get("prompt_chat_id")

    await _try_delete(message)

    query = (message.text or "").strip()
    if not query:
        if prompt_msg_id:
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="banned_words"))
            await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id,
                               "⚠️ Введите слово для поиска:", builder.as_markup())
        return

    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        rt_repo = RouteRepository(session)
        results = await repo.search(query)
        route_names: dict[int, str] = {}
        for w in results:
            if w.route_id and w.route_id not in route_names:
                r = await rt_repo.get_route_by_id(w.route_id)
                if r:
                    src = r.source.title or r.source.username or f"#{r.source_id}" if r.source else f"#{r.source_id}"
                    dst = r.destination.title or r.destination.username or f"#{r.destination_id}" if r.destination else f"#{r.destination_id}"
                    route_names[w.route_id] = f"{src[:15]}→{dst[:15]}"

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔍 Ещё поиск", callback_data="bw_search"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="banned_words"))

    if not results:
        text = f"🔍 По запросу «<b>{query}</b>»:\n\n❌ Не найдено"
    else:
        lines = []
        for w in results:
            scope = "🌍 Глобально" if w.route_id is None else f"🎯 {route_names.get(w.route_id, f'маршрут #{w.route_id}')}"
            kind = "🟢 Исключение" if w.is_exception else "✅ Добавлено"
            lines.append(f"{kind} — <code>{w.word}</code> ({scope})")
        text = f"🔍 По запросу «<b>{query}</b>»:\n\n" + "\n".join(lines)

    if prompt_msg_id:
        await _edit_prompt(message.bot, prompt_chat_id, prompt_msg_id, text, builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("bw_del:"))
async def cb_bw_delete(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    word_id = int(parts[1])
    back = parts[2] if len(parts) > 2 else "global"

    async with async_session_factory() as session:
        repo = BannedWordRepository(session)
        await repo.delete_by_id(word_id)
        await session.commit()

    await callback.answer("✅ Удалено")

    if back == "global":
        await cb_bw_global(callback, state)
    elif back == "route" and len(parts) > 3:
        route_id = int(parts[3])
        await _show_route_words(callback.message, route_id, edit=True)
    else:
        await cb_bw_global(callback, state)
