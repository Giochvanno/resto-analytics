"""Настройки приложения из переменных окружения (префикс RESTO_)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config/summary.toml")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESTO_", env_file=".env", extra="ignore")

    max_upload_mb: float = Field(default=10, gt=0, le=100)
    summary_config: Path | None = DEFAULT_CONFIG_PATH
    log_level: str = "INFO"

    bot_token: SecretStr | None = None
    """Токен Telegram-бота от @BotFather. SecretStr — чтобы не утёк в логи и repr."""
    bot_allowed_users: str = ""
    """Telegram ID через запятую: «123456789, 987654321»."""

    @field_validator("bot_allowed_users")
    @classmethod
    def _ids_are_numbers(cls, value: str) -> str:
        bad = [part for part in _split_ids(value) if not part.isdigit()]
        if bad:
            raise ValueError(f"Telegram ID должны быть числами, а не: {', '.join(bad)}")
        return value

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def allowed_user_ids(self) -> frozenset[int]:
        return frozenset(int(part) for part in _split_ids(self.bot_allowed_users))


def _split_ids(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
