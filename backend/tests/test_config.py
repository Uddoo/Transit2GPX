from __future__ import annotations

from pathlib import Path

from app.core.config import Settings


def test_transit2fog_environment_variables_take_precedence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("METRO2FOG_PORT", "8001")
    monkeypatch.setenv("TRANSIT2FOG_PORT", "8002")

    settings = Settings(_env_file=None)

    assert settings.port == 8002


def test_legacy_metro2fog_environment_variables_remain_supported(
    monkeypatch,
    tmp_path: Path,
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("TRANSIT2FOG_DATA_DIR", raising=False)
    monkeypatch.delenv("TRANSIT2FOG_DATABASE_URL", raising=False)
    monkeypatch.setenv("METRO2FOG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "METRO2FOG_DATABASE_URL",
        f"sqlite:///{tmp_path / 'legacy.sqlite3'}",
    )

    settings = Settings(_env_file=None)

    assert settings.data_dir == tmp_path
    assert settings.resolved_database_url.endswith("legacy.sqlite3")


def test_new_default_database_uses_transit2fog_filename(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, database_url=None, _env_file=None)

    assert settings.resolved_database_url.endswith("transit2fog.sqlite3")


def test_existing_legacy_database_is_discovered(tmp_path: Path) -> None:
    legacy_database = tmp_path / "metro2fog.sqlite3"
    legacy_database.touch()
    settings = Settings(data_dir=tmp_path, database_url=None, _env_file=None)

    assert settings.resolved_database_url.endswith("metro2fog.sqlite3")
