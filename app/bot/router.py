"""Main aiogram router combining all sub-routers."""
from __future__ import annotations

from aiogram import Router

from app.bot.handlers import bulk_import, destinations, import_excel, join_channels, refresh_sources, sources, start, status, sync_dialogs
from app.bot.handlers import banned_words, text_replacements

main_router = Router(name="main")

# Include all sub-routers
main_router.include_router(banned_words.router)
main_router.include_router(text_replacements.router)
main_router.include_router(start.router)
main_router.include_router(sources.router)
main_router.include_router(destinations.router)
main_router.include_router(status.router)
main_router.include_router(import_excel.router)
main_router.include_router(sync_dialogs.router)
main_router.include_router(bulk_import.router)
main_router.include_router(join_channels.router)
main_router.include_router(refresh_sources.router)
