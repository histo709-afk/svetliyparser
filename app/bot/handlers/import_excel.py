"""Handler for bulk import from Excel file."""
from __future__ import annotations

import asyncio
import io
from aiogram import F, Router
from aiogram.types import Message, Document

from app.bot.keyboards import back_to_menu_keyboard
from app.database import async_session_factory
from app.services.channel_service import (
    add_source_channel, add_destination_channel, create_route, resolve_channel,
    join_channel_link,
)

router = Router(name="import")


def _get_telethon_client():
    from app.telethon_client.client import telethon_client
    return telethon_client


@router.message(F.document)
async def handle_excel_import(message: Message) -> None:
    doc: Document = message.document
    if not doc.file_name or not doc.file_name.endswith((".xlsx", ".xls")):
        await message.answer("⚠️ Отправьте файл Excel (.xlsx или .xls)")
        return

    await message.answer("📊 Обрабатываю файл, это может занять несколько минут...")

    try:
        import openpyxl
    except ImportError:
        await message.answer("❌ Библиотека openpyxl не установлена на сервере.")
        return

    # Download file
    file = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file.file_path)
    content = file_bytes.read() if hasattr(file_bytes, 'read') else file_bytes

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        await message.answer(f"❌ Ошибка чтения файла: {e}")
        return

    if len(rows) < 1:
        await message.answer("❌ Файл пустой.")
        return

    # Try to locate "Источник" / "Назначение" columns by header name first —
    # handles files with extra columns (city name, numeric dest ID, ...) in
    # any order. Falls back to "last two non-empty cells" for simple files
    # with no header or unrecognized header text.
    def _find_header_cols(header_row):
        if not header_row:
            return None
        src_col = dst_col = None
        for i, cell in enumerate(header_row):
            name = str(cell or "").strip().lower()
            if "источник" in name and src_col is None:
                src_col = i
            elif "назначен" in name and "id" not in name and dst_col is None:
                dst_col = i
        if src_col is not None and dst_col is not None:
            return src_col, dst_col
        return None

    def _extract_links_by_index(row, src_col, dst_col):
        if not row or len(row) <= max(src_col, dst_col):
            return None
        src = row[src_col]
        dst = row[dst_col]
        if src in (None, "") or dst in (None, ""):
            return None
        return str(src).strip(), str(dst).strip()

    def _extract_links_positional(row):
        if not row:
            return None
        cells = [str(c).strip() for c in row if c not in (None, "")]
        if len(cells) < 2:
            return None
        return cells[-2], cells[-1]

    header_cols = _find_header_cols(rows[0]) if rows else None

    if header_cols:
        src_col, dst_col = header_cols
        data_rows = [
            pair for pair in (_extract_links_by_index(r, src_col, dst_col) for r in rows[1:])
            if pair
        ]
    else:
        def _looks_like_data(row) -> bool:
            pair = _extract_links_positional(row)
            if not pair:
                return False
            joined = " ".join(pair)
            return "t.me/" in joined or "http" in joined

        raw_rows = rows if _looks_like_data(rows[0]) else rows[1:]
        data_rows = [pair for pair in (_extract_links_positional(r) for r in raw_rows) if pair]

    if not data_rows:
        await message.answer("❌ Файл пустой или содержит только заголовки.")
        return

    client = _get_telethon_client()

    # Pre-resolve all unique destination links once to avoid rate limits.
    # First JOIN each destination (needed for private invite links to resolve).
    unique_dest_links = {dest for _, dest in data_rows}

    dest_cache: dict[str, object] = {}
    dest_errors: dict[str, str] = {}
    for link in unique_dest_links:
        try:
            await join_channel_link(client, link)
            await asyncio.sleep(1)
            info = await resolve_channel(client, link)
            if info:
                dest_cache[link] = info
            else:
                dest_errors[link] = f"Не удалось найти канал по ссылке: {link}"
        except Exception as e:
            dest_errors[link] = f"[{type(e).__name__}] {str(e)[:80]}"
        await asyncio.sleep(2)  # avoid flood limits

    added = 0
    skipped = 0
    errors = []

    for i, (source_link, dest_link) in enumerate(data_rows, start=2):
        if dest_link in dest_errors:
            errors.append(f"Строка {i}: {source_link} → {dest_errors[dest_link][:60]}")
            if len(errors) >= 10:
                errors.append("...и другие ошибки")
                break
            continue

        try:
            # Join the source channel so the userbot can actually read its posts
            await join_channel_link(client, source_link)
            await asyncio.sleep(1)
            async with async_session_factory() as session:
                src, _ = await add_source_channel(session, client, source_link)
                dst, _ = await add_destination_channel(session, client, dest_link)
                _, created = await create_route(session, src.id, dst.id)
                await session.commit()

            if created:
                added += 1
            else:
                skipped += 1
        except Exception as e:
            errors.append(f"Строка {i}: {source_link} → {str(e)[:60]}")
            if len(errors) >= 10:
                errors.append("...и другие ошибки")
                break

    text = f"✅ <b>Импорт завершён!</b>\n\n"
    text += f"• Добавлено маршрутов: <b>{added}</b>\n"
    text += f"• Уже существовало: <b>{skipped}</b>\n"
    if errors:
        text += f"\n⚠️ Ошибки ({len(errors)}):\n"
        text += "\n".join(errors[:10])

    await message.answer(text, reply_markup=back_to_menu_keyboard(), parse_mode="HTML")
