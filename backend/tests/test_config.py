from __future__ import annotations

from pathlib import Path

import pytest

from app.core import config
from app.core.config import Settings


def test_transit2gpx_environment_variables_take_precedence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("METRO2FOG_PORT", "8001")
    monkeypatch.setenv("TRANSIT2FOG_PORT", "8003")
    monkeypatch.setenv("TRANSIT2GPX_PORT", "8002")

    settings = Settings(_env_file=None)

    assert settings.port == 8002


def test_transit2fog_environment_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRANSIT2GPX_PORT", raising=False)
    monkeypatch.setenv("TRANSIT2FOG_PORT", "8003")
    monkeypatch.setenv("METRO2FOG_PORT", "8001")
    assert Settings(_env_file=None).port == 8003


@pytest.mark.parametrize("legacy_name", ["Transit2Fog", "Metro2Fog"])
def test_default_data_directory_fallback_and_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_name: str
) -> None:
    monkeypatch.setattr(config, "user_data_path", lambda name, **kw: tmp_path / name)
    assert config._default_data_dir() == tmp_path / "Transit2GPX"
    legacy = tmp_path / legacy_name
    legacy.mkdir()
    assert config._default_data_dir() == legacy
    current = tmp_path / "Transit2GPX"
    current.mkdir()
    assert config._default_data_dir() == current


def test_existing_transit2fog_database_and_current_priority(tmp_path: Path) -> None:
    legacy = tmp_path / "transit2fog.sqlite3"
    legacy.touch()
    settings = Settings(data_dir=tmp_path, database_url=None, _env_file=None)
    assert settings.resolved_database_url.endswith("transit2fog.sqlite3")
    (tmp_path / "transit2gpx.sqlite3").touch()
    assert settings.resolved_database_url.endswith("transit2gpx.sqlite3")


def test_legacy_metro2fog_environment_variables_remain_supported(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TRANSIT2GPX_DATA_DIR", raising=False)
    monkeypatch.delenv("TRANSIT2GPX_DATABASE_URL", raising=False)
    monkeypatch.setenv("METRO2FOG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "METRO2FOG_DATABASE_URL",
        f"sqlite:///{tmp_path / 'legacy.sqlite3'}",
    )

    settings = Settings(_env_file=None)

    assert settings.data_dir == tmp_path
    assert settings.resolved_database_url.endswith("legacy.sqlite3")


def test_new_default_database_uses_transit2gpx_filename(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, database_url=None, _env_file=None)

    assert settings.resolved_database_url.endswith("transit2gpx.sqlite3")


def test_existing_legacy_database_is_discovered(tmp_path: Path) -> None:
    legacy_database = tmp_path / "metro2fog.sqlite3"
    legacy_database.touch()
    settings = Settings(data_dir=tmp_path, database_url=None, _env_file=None)

    assert settings.resolved_database_url.endswith("metro2fog.sqlite3")
