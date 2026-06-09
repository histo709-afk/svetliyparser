from __future__ import annotations

from typing import List

from pydantic import field_validator
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
    LOG_LEVEL: str = "INFO"

    @property
    def admin_ids_list(self) -> List[int]:
        import os
        raw = os.environ.get("ADMIN_IDS", self.ADMIN_IDS)
        print(f"RAW_ADMIN_IDS={repr(raw)}", flush=True)
        return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]


settings = Settings()
