"""Entry point: starts both Telethon userbot and aiogram management bot."""
from __future__ import annotations

import asyncio
import logging
import os
import signal

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
from app.telethon_client.client import (
    SessionLockUnavailableError,
    SessionRevokedError,
    release_session_lock,
    shutdown_client,
    start_client,
    userbot_status,
)
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


def _build_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


async def alert_admins(bot: Bot, text: str) -> None:
    """Push an operational alert to the admins over the *bot* API.

    Deliberately not the userbot: the alerts that matter most are the ones
    about the userbot being dead, and a dead userbot cannot report itself.
    """
    targets = list(settings.admin_ids_list)
    if settings.NOTIFICATIONS_CHAT_ID:
        targets.append(settings.NOTIFICATIONS_CHAT_ID)
    for chat_id in dict.fromkeys(targets):
        try:
            await bot.send_message(chat_id, text)
        except Exception as exc:
            log.warning("alert_admin_failed", chat_id=chat_id, error=str(exc)[:120])


async def start_aiogram_bot(bot: Bot, redis_client) -> None:
    """Initialize and run the aiogram management bot."""
    storage = RedisStorage(redis=redis_client)
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
        BotCommand(command="resetroute", description="Сбросить маршрут начисто"),
        BotCommand(command="joinall", description="Довступить во все источники"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    log.info("starting_aiogram_bot")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


async def start_telethon(bot: Bot) -> None:
    """Start the userbot, or report clearly why it could not start.

    A dead session used to raise straight out of asyncio.gather and take the
    management bot down with it, so the one tool for diagnosing the outage
    died alongside the outage. Now the userbot fails on its own and the admin
    gets told what to do about it.
    """
    log.info("starting_telethon_client")
    warned_about_lock = False
    while True:
        try:
            client = await start_client()
            break
        except SessionLockUnavailableError as exc:
            # The outgoing container is taking its time. Waiting is the whole
            # point — connecting anyway is what revoked the session in the
            # first place — so keep queueing rather than giving up.
            userbot_status.mark_dead(str(exc))
            log.warning("userbot_waiting_for_lock", error=str(exc))
            if not warned_about_lock:
                await alert_admins(
                    bot,
                    "⏳ <b>Юзербот ждёт освобождения сессии.</b>\n\n"
                    "Предыдущий контейнер ещё держит её. Подключаться сейчас "
                    "нельзя — именно так сессия и убивается. Продолжаю ждать.",
                )
                warned_about_lock = True
            await asyncio.sleep(60)
        except SessionRevokedError as exc:
            userbot_status.mark_dead(str(exc))
            log.error("userbot_session_dead", error=str(exc))
            await alert_admins(
                bot,
                "⛔ <b>Сессия юзербота мертва — пересылка стоит.</b>\n\n"
                f"<code>{exc}</code>\n\n"
                "Что делать:\n"
                "1. Локально: <code>python3 generate_session.py</code>\n"
                "2. Railway → svetliyparser → Variables → "
                "<code>TELEGRAM_SESSION_STRING</code> → вставить новую строку\n"
                "3. Сохранение само вызовет <b>ровно один</b> редеплой. "
                "Больше ничего не нажимать.",
            )
            return

    userbot_status.mark_alive()
    log.info("telethon_authenticated")
    # Sync all joined channels into Telethon's entity cache so get_messages() works
    log.info("syncing_dialogs")
    async for _ in client.iter_dialogs():
        pass
    log.info("dialogs_synced")
    # Fix all stale telegram_ids using dialog entity cache (no flood limits)
    await fix_all_stale_ids(client)
    try:
        # run_listener, poll_sources, and run_until_disconnected run concurrently
        await asyncio.gather(
            run_listener(client),
            poll_sources(client),
            client.run_until_disconnected(),
        )
    finally:
        userbot_status.mark_dead("userbot stopped")
        # Disconnect before releasing: the next container starts connecting the
        # instant the lock is free, and an overlap is what revokes the session.
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        await release_session_lock()


def _install_shutdown_handler() -> None:
    """Release the session lock when Railway tears this container down.

    Railway SIGTERMs the outgoing container on every deploy, and the default
    disposition kills the process outright — no `finally` blocks, so the lock
    would linger until its TTL and the incoming container would idle for the
    remainder. Handling the signal lets us disconnect and hand over at once.
    """
    loop = asyncio.get_running_loop()

    async def terminate() -> None:
        log.info("sigterm_received")
        await shutdown_client()
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(terminate()))
        except NotImplementedError:
            # Not supported on this platform — the lock TTL still covers us.
            log.warning("signal_handler_unavailable", signal=sig)


async def main() -> None:
    from redis.asyncio import from_url as redis_from_url

    _install_shutdown_handler()

    log.info("initializing_database")
    await init_db()
    log.info("database_ready")

    bot = _build_bot()
    redis_client = redis_from_url(settings.REDIS_URL)
    try:
        # return_exceptions keeps one half's failure from cancelling the other:
        # the management bot has to outlive the userbot to be any use.
        results = await asyncio.gather(
            start_telethon(bot),
            start_aiogram_bot(bot, redis_client),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                log.error("task_crashed", error=repr(result))
    finally:
        await release_session_lock()
        await bot.session.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
