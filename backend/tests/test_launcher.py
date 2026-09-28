from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings, get_settings
from app.launcher import (
    _configure_environment,
    main,
    package_smoke_test,
    upgrade_database,
)


def test_packaged_launcher_upgrades_an_isolated_database(tmp_path: Path) -> None:
    database = tmp_path / "package.sqlite3"
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{database.as_posix()}",
        _env_file=None,
    )

    logger = logging.getLogger("app")
    logger.disabled = False
    upgrade_database(settings)

    assert not logger.disabled
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260928_0009",)
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_task'"
        ).fetchone() == ("app_task",)


def test_launcher_configures_all_runtime_overrides(tmp_path: Path) -> None:
    environment_names = (
        "TRANSIT2FOG_ENVIRONMENT",
        "TRANSIT2FOG_FRONTEND_DIST",
        "TRANSIT2FOG_DATA_DIR",
        "TRANSIT2FOG_HOST",
        "TRANSIT2FOG_PORT",
        "TRANSIT2FOG_RAIL_ENABLED",
        "TRANSIT2FOG_RAIL_SIDECAR_MANAGED",
        "TRANSIT2FOG_RAIL_GRAPH_VERSION",
        "TRANSIT2FOG_RAIL_GRAPH_ROOT",
        "TRANSIT2FOG_RAIL_PBF_PATH",
        "TRANSIT2FOG_RAIL_SIDECAR_JAR",
    )
    original_environment = {name: os.environ.get(name) for name in environment_names}
    for name in environment_names:
        os.environ.pop(name, None)
    args = argparse.Namespace(
        data_dir=tmp_path / "data",
        host="localhost",
        port=9876,
        rail=True,
        rail_graph_root=tmp_path / "graphs",
        rail_pbf=tmp_path / "rail.osm.pbf",
        rail_sidecar_jar=tmp_path / "sidecar.jar",
    )

    try:
        settings = _configure_environment(args)

        assert settings.environment == "production"
        assert settings.host == "localhost"
        assert settings.port == 9876
        assert settings.rail_enabled
        assert settings.rail_sidecar_managed
        assert settings.rail_graph_version == "active"
        assert settings.resolved_rail_graph_root == (tmp_path / "graphs").resolve()
        assert settings.rail_pbf_path == (tmp_path / "rail.osm.pbf").resolve()
        assert (
            settings.resolved_rail_sidecar_jar == (tmp_path / "sidecar.jar").resolve()
        )
    finally:
        for name, value in original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        get_settings.cache_clear()


def test_package_smoke_test_checks_api_and_geospatial_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text("server: {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.main.create_app", lambda: SimpleNamespace(routes=[object()])
    )
    settings = Settings(
        data_dir=tmp_path,
        rail_sidecar_config=config_path,
        _env_file=None,
    )

    package_smoke_test(settings)


def test_launcher_smoke_mode_migrates_without_starting_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frontend_dist = tmp_path / "frontend"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").touch()
    settings = Settings(
        data_dir=tmp_path,
        frontend_dist=frontend_dist,
        _env_file=None,
    )
    calls: list[str] = []
    monkeypatch.setattr(sys, "argv", ["Transit2Fog", "--smoke-test", "--no-browser"])
    monkeypatch.setattr("app.launcher._configure_environment", lambda args: settings)
    monkeypatch.setattr(
        "app.launcher.upgrade_database", lambda value: calls.append("upgrade")
    )
    monkeypatch.setattr(
        "app.launcher.package_smoke_test", lambda value: calls.append("smoke")
    )

    main()

    assert calls == ["upgrade", "smoke"]
