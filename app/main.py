"""Entry point: starts both Telethon userbot and aiogram management bot."""
from __future__ import annotations

import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, MenuButtonCommands

from app.bot.middlewares import AdminMiddleware
from app.bot.router import main_router
from app.config import settings
from app.database import init_db
from app.telethon_client.client import start_client
from app.services.sync_service import poll_sources
from app.telethon_client.listener import fix_all_stale_ids, run_listener

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

log = structlog.get_logger(__name__)


async def start_aiogram_bot() -> None:
    """Initialize and run the aiogram management bot."""
    from redis.asyncio import from_url as redis_from_url

    redis_client = redis_from_url(settings.REDIS_URL)
    storage = RedisStorage(redis=redis_client)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=storage)

    # Apply admin middleware to all updates
    dp.message.middleware(AdminMiddleware())
    dp.callback_query.middleware(AdminMiddleware())

    dp.include_router(main_router)

    # The chat "Menu" button next to the text input is a bot-level default —
    # unlike a reply keyboard, it shows up immediately for every user, even
    # before they've ever sent /start or received any message from the bot.
    await bot.set_my_commands([
        BotCommand(command="start", description="Открыть главное меню"),
        BotCommand(command="newcity", description="Создать канал для нового города"),
        BotCommand(command="collectsources", description="Автопоиск источников для города"),
        BotCommand(command="routes", description="Маршруты пересылки"),
        BotCommand(command="status", description="Статус системы"),
        BotCommand(command="logs", description="Последние ошибки"),
        BotCommand(command="resync", description="Подхватить последние посты"),
        BotCommand(command="joinall", description="Довступить во все источники"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    log.info("starting_aiogram_bot")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()
        await redis_client.aclose()


async def start_telethon() -> None:
    """Start Telethon client and listener."""
    log.info("starting_telethon_client")
    client = await start_client()
    log.info("telethon_authenticated")
    # Sync all joined channels into Telethon's entity cache so get_messages() works
    log.info("syncing_dialogs")
    async for _ in client.iter_dialogs():
        pass
    log.info("dialogs_synced")
    # Fix all stale telegram_ids using dialog entity cache (no flood limits)
    await fix_all_stale_ids(client)
    # run_listener, poll_sources, and run_until_disconnected run concurrently
    await asyncio.gather(
        run_listener(client),
        poll_sources(client),
        client.run_until_disconnected(),
    )


async def main() -> None:
    log.info("initializing_database")
    await init_db()
    log.info("database_ready")

    await asyncio.gather(
        start_telethon(),
        start_aiogram_bot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
