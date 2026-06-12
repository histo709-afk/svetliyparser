"""Main aiogram router combining all sub-routers."""
from __future__ import annotations

from aiogram import Router

from app.bot.handlers import destinations, import_excel, sources, start, status, sync_dialogs

main_router = Router(name="main")

# Include all sub-routers
main_router.include_router(start.router)
main_router.include_router(sources.router)
main_router.include_router(destinations.router)
main_router.include_router(status.router)
main_router.include_router(import_excel.router)
main_router.include_router(sync_dialogs.router)
