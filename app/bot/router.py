"""Main aiogram router combining all sub-routers."""
from __future__ import annotations

from aiogram import Router

from app.bot.handlers import bulk_import, collect_sources, destinations, escape_state, import_excel, join_channels, new_city, refresh_sources, sources, start, status, sync_dialogs
from app.bot.handlers import banned_words, text_replacements, required_keywords

main_router = Router(name="main")

# Include all sub-routers.
# escape_state goes first: it lets a command cancel a half-finished wizard
# instead of being swallowed by that wizard's bare state filter.
main_router.include_router(escape_state.router)
main_router.include_router(banned_words.router)
main_router.include_router(required_keywords.router)
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
main_router.include_router(new_city.router)
main_router.include_router(collect_sources.router)
