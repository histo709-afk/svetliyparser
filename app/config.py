from __future__ import annotations

import os
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str
    TELEGRAM_PHONE: str
    DATABASE_URL: str
    REDIS_URL: str
    SESSION_NAME: str = "userbot"
    TELEGRAM_SESSION_STRING: str = ""
    LOG_LEVEL: str = "INFO"
    NOTIFICATIONS_CHAT_ID: int = 0

    @property
    def admin_ids_list(self) -> List[int]:
        raw = os.environ.get("ADMIN_IDS", self.ADMIN_IDS)
        return [int(x.strip()) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]


settings = Settings()
