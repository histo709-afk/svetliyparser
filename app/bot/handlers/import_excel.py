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

    # Detect whether the first row is a header or actual data.
    # If the first row already contains a t.me/http link, treat all rows as data.
    def _looks_like_data(row) -> bool:
        if not row:
            return False
        joined = " ".join(str(c) for c in row if c)
        return "t.me/" in joined or "http" in joined

    data_rows = rows if _looks_like_data(rows[0]) else rows[1:]
    if not data_rows:
        await message.answer("❌ Файл пустой или содержит только заголовки.")
        return

    client = _get_telethon_client()

    # Pre-resolve all unique destination links once to avoid rate limits.
    # First JOIN each destination (needed for private invite links to resolve).
    unique_dest_links = set()
    for row in data_rows:
        if row and len(row) >= 3 and row[2]:
            unique_dest_links.add(str(row[2]).strip())

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

    for i, row in enumerate(data_rows, start=2):
        if not row or len(row) < 3:
            continue
        _, source_link, dest_link = row[0], row[1], row[2]
        if not source_link or not dest_link:
            continue

        source_link = str(source_link).strip()
        dest_link = str(dest_link).strip()

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
