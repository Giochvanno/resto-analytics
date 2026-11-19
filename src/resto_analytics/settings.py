"""Настройки приложения из переменных окружения (префикс RESTO_)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config/summary.toml")


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESTO_", env_file=".env", extra="ignore")

    max_upload_mb: float = Field(default=10, gt=0, le=100)
    summary_config: Path | None = DEFAULT_CONFIG_PATH
    log_level: str = "INFO"

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)
