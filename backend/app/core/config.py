from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from platformdirs import user_data_path
from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _environment_alias(name: str) -> AliasChoices:
    return AliasChoices(f"TRANSIT2FOG_{name}", f"METRO2FOG_{name}")


def _default_data_dir() -> Path:
    current = user_data_path("Transit2Fog", appauthor=False)
    legacy = user_data_path("Metro2Fog", appauthor=False)
    return legacy if not current.exists() and legacy.exists() else current


class Settings(BaseSettings):
    """Runtime settings loaded from TRANSIT2FOG_* or legacy METRO2FOG_* variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(
        default="Transit2Fog", validation_alias=_environment_alias("APP_NAME")
    )
    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=_environment_alias("ENVIRONMENT"),
    )
    host: str = Field(default="127.0.0.1", validation_alias=_environment_alias("HOST"))
    port: int = Field(default=8765, validation_alias=_environment_alias("PORT"))
    data_dir: Path = Field(
        default_factory=_default_data_dir,
        validation_alias=_environment_alias("DATA_DIR"),
    )
    database_url: str | None = Field(
        default=None, validation_alias=_environment_alias("DATABASE_URL")
    )
    frontend_dist: Path | None = Field(
        default=None, validation_alias=_environment_alias("FRONTEND_DIST")
    )
    map_tiles_enabled: bool = Field(
        default=True, validation_alias=_environment_alias("MAP_TILES_ENABLED")
    )
    map_tile_url: str = Field(
        default="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        validation_alias=_environment_alias("MAP_TILE_URL"),
    )
    map_tile_attribution: str = Field(
        default=(
            '&copy; <a href="https://www.openstreetmap.org/copyright">'
            "OpenStreetMap</a> contributors"
        ),
        validation_alias=_environment_alias("MAP_TILE_ATTRIBUTION"),
    )
    map_max_zoom: int = Field(
        default=19, validation_alias=_environment_alias("MAP_MAX_ZOOM")
    )
    station_search_min_score: int = Field(
        default=65,
        ge=0,
        le=100,
        validation_alias=_environment_alias("STATION_SEARCH_MIN_SCORE"),
    )
    rail_enabled: bool = Field(
        default=False, validation_alias=_environment_alias("RAIL_ENABLED")
    )
    rail_sidecar_url: str = Field(
        default="http://127.0.0.1:8989",
        validation_alias=_environment_alias("RAIL_SIDECAR_URL"),
    )
    rail_sidecar_timeout_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=30.0,
        validation_alias=_environment_alias("RAIL_SIDECAR_TIMEOUT_SECONDS"),
    )
    rail_graph_version: str | None = Field(
        default=None,
        validation_alias=_environment_alias("RAIL_GRAPH_VERSION"),
    )
    rail_graph_root: Path | None = Field(
        default=None,
        validation_alias=_environment_alias("RAIL_GRAPH_ROOT"),
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        database_path = self.data_dir / "transit2fog.sqlite3"
        legacy_database_path = self.data_dir / "metro2fog.sqlite3"
        if not database_path.exists() and legacy_database_path.exists():
            database_path = legacy_database_path
        database_path = database_path.resolve()
        return f"sqlite:///{database_path}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_frontend_dist(self) -> Path:
        if self.frontend_dist:
            return self.frontend_dist.resolve()
        return Path(__file__).resolve().parents[3] / "frontend" / "dist"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_rail_graph_root(self) -> Path:
        if self.rail_graph_root:
            return self.rail_graph_root.resolve()
        return (self.data_dir / "rail-routing" / "graphs").resolve()

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
