from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from platformdirs import user_data_path
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from METRO2FOG_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="METRO2FOG_",
        extra="ignore",
    )

    app_name: str = "Metro2Fog"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = user_data_path("Metro2Fog", appauthor=False)
    database_url: str | None = None
    frontend_dist: Path | None = None
    map_tiles_enabled: bool = True
    map_tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_tile_attribution: str = (
        '&copy; <a href="https://www.openstreetmap.org/copyright">'
        "OpenStreetMap</a> contributors"
    )
    map_max_zoom: int = 19
    station_search_min_score: int = Field(default=65, ge=0, le=100)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        database_path = (self.data_dir / "metro2fog.sqlite3").resolve()
        return f"sqlite:///{database_path}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_frontend_dist(self) -> Path:
        if self.frontend_dist:
            return self.frontend_dist.resolve()
        return Path(__file__).resolve().parents[3] / "frontend" / "dist"

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
