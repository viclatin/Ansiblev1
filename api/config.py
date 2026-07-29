from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API key Power BI will send via the X-API-Key request header.
    # Leave empty to disable auth (local dev only).
    api_key: str = ""

    # Allowed CORS origins. Use "*" to allow all (Power BI Service requires this
    # when calling from browser-based refresh). Comma-separated list.
    cors_origins: str = "*"

    # Absolute path to the directory that contains the Power BI CSV exports.
    powerbi_data_dir: Path = Path(__file__).resolve().parent.parent / "reports" / "powerbi"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
