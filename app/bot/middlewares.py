"""Admin check middleware for aiogram."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from app.config import settings


class AdminMiddleware(BaseMiddleware):
    """Reject non-admin users with a polite message."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        import logging
        logging.getLogger(__name__).warning(
            "ACCESS_CHECK user_id=%s admin_ids=%s allowed=%s",
            user.id if user else None,
            settings.ADMIN_IDS,
            user is not None and user.id in settings.ADMIN_IDS,
        )
        if user is None or user.id not in settings.ADMIN_IDS:
            # Try to answer if the event is a message or callback
            from aiogram.types import Message, CallbackQuery

            if isinstance(event, Message):
                await event.answer("⛔ Доступ запрещён.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        return await handler(event, data)
