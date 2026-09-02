from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_id: str | None = os.getenv("TELEGRAM_ALLOWED_USER_ID")
    sync_secret: str | None = os.getenv("SYNC_SECRET")
    public_base_url: str | None = os.getenv("PUBLIC_BASE_URL")


settings = Settings()
