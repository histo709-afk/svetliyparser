"""/joinqueue — progress of the background source-joining queue."""
from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.join_queue import JOIN_QUEUE_INTERVAL, queue_stats

router = Router(name="join_queue")


@router.message(Command("joinqueue"))
async def cmd_join_queue(message: Message) -> None:
    stats = await queue_stats()
    if not stats["batches"]:
        await message.answer("📭 Очередь подключения пуста.")
        return

    lines = ["📥 <b>Очередь подключения источников</b>\n"]
    for batch, counts in stats["batches"].items():
        pending = counts.get("pending", 0)
        lines.append(
            f"<b>{escape(batch)}</b>: ✅ {counts.get('done', 0)} · "
            f"⏳ {pending} · ❌ {counts.get('failed', 0)}"
        )
        if pending:
            hours = pending * JOIN_QUEUE_INTERVAL / 3600
            lines.append(f"   осталось примерно {hours:.0f} ч. без учёта пауз Telegram")

    if stats["failed"]:
        lines.append("\n<b>Последние ошибки:</b>")
        for item in stats["failed"]:
            name = escape(item.title or item.link)
            lines.append(f"• {name} — {escape(item.error or '?')}")

    await message.answer("\n".join(lines), disable_web_page_preview=True)
