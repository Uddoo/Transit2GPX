from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest
from factories import seed_linear_network
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_sidecar_supervisor import _info, _settings

from app.core.config import Settings
from app.db.base import AppMeta
from app.rail.service import RailServiceController
from app.rail.sidecar import RailSidecarError
from app.services.onboarding import (
    RailSetupConfig,
    current_rail_config,
    environment_checks,
    get_progress,
    rail_checks,
    restore_rail_preferences,
    save_rail_preferences,
)


@pytest.fixture(autouse=True)
def setup_storage(db: Session) -> Generator[None]:
    db.execute(delete(AppMeta).where(AppMeta.key.like("setup.%")))
    db.commit()
    yield
    db.execute(delete(AppMeta).where(AppMeta.key.like("setup.%")))
    db.commit()


def test_first_run_progress_dismissal_and_completion_guard(
    client: TestClient, tmp_path: Path
) -> None:
    state = client.get("/api/v1/setup").json()
    assert state["should_show"] and state["progress"]["step"] == "check"
    assert client.get("/api/v1/setup/checks").json()["can_continue"]
    assert (
        client.patch("/api/v1/setup/progress", json={"complete": True}).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/v1/setup/progress",
            json={"step": "metro", "metro_directory": str(tmp_path)},
        ).status_code
        == 200
    )
    state = client.get("/api/v1/setup").json()
    assert state["progress"]["step"] == "metro"
    assert state["metro_directory"] == str(tmp_path)
    client.patch("/api/v1/setup/progress", json={"dismissed": True})
    assert not client.get("/api/v1/setup").json()["should_show"]
    client.patch(
        "/api/v1/setup/progress",
        json={"dismissed": False, "rail_skipped": True, "step": "finish"},
    )
    assert client.get("/api/v1/setup").json()["should_show"]
    assert (
        client.patch(
            "/api/v1/setup/progress", json={"metro_directory": "x" * 481}
        ).status_code
        == 422
    )


def test_existing_users_are_not_forced_through_setup_and_can_complete(
    client: TestClient, db: Session
) -> None:
    seed_linear_network(db)
    assert not client.get("/api/v1/setup").json()["should_show"]
    response = client.patch("/api/v1/setup/progress", json={"complete": True})
    assert response.json()["completed"]
    assert response.json()["step"] == "finish"


def test_environment_failures_block_completion(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    seed_linear_network(db)
    monkeypatch.setattr(
        "app.services.onboarding.schema_head", lambda: "missing-migration"
    )
    monkeypatch.setattr("app.services.onboarding.os.access", lambda *args: False)
    monkeypatch.setattr(
        "app.services.onboarding.shutil.disk_usage",
        lambda *args: SimpleNamespace(free=100),
    )
    checks = environment_checks(db, get_settings())
    assert not checks.can_continue
    assert {item.id for item in checks.checks if item.status == "failed"} == {
        "database",
        "storage",
    }
    assert checks.checks[-1].status == "warning"
    assert (
        client.patch("/api/v1/setup/progress", json={"complete": True}).json()["error"][
            "code"
        ]
        == "setup_environment_not_ready"
    )

    def inaccessible(*args: object) -> None:
        raise OSError("unmounted")

    monkeypatch.setattr("app.services.onboarding.shutil.disk_usage", inaccessible)
    assert environment_checks(db, get_settings()).checks[-1].status == "warning"


def test_rail_checks_detect_version_missing_files_and_matching_external_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)

    def unavailable(*args: object) -> None:
        raise RailSidecarError("rail_sidecar_unavailable", "stopped")

    monkeypatch.setattr("app.services.onboarding.fetch_sidecar_info", unavailable)
    monkeypatch.setattr(
        "app.services.onboarding.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "", 'openjdk version "21.0.1"'
        ),
    )
    assert rail_checks(settings).can_continue
    monkeypatch.setattr(
        "app.services.onboarding.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "", 'java version "1.8.0"'
        ),
    )
    assert not rail_checks(settings).can_continue
    settings.resolved_rail_sidecar_jar.unlink()
    assert any(
        item.id == "jar" and item.status == "failed"
        for item in rail_checks(settings).checks
    )
    monkeypatch.setattr(
        "app.services.onboarding.fetch_sidecar_info", lambda *args: _info()
    )
    assert rail_checks(settings).can_continue  # reuse works without a local JAR/JVM
    monkeypatch.setattr(
        "app.services.onboarding.fetch_sidecar_info",
        lambda *args: _info(graph_version="other"),
    )
    assert rail_checks(settings).checks[0].id == "service_identity"


def test_rail_check_missing_java_and_graph_and_path_validation(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*args: object) -> None:
        raise RailSidecarError("rail_java_missing", "missing")

    monkeypatch.setattr("app.services.onboarding._java_executable", missing)
    response = client.post(
        "/api/v1/setup/rail/check",
        json={"graph_root": str(tmp_path), "graph_version": "missing"},
    )
    assert response.status_code == 200
    assert not response.json()["can_continue"]
    assert any(check["id"] == "graph_files" for check in response.json()["checks"])
    assert (
        client.post(
            "/api/v1/setup/rail/check", json={"graph_root": "relative"}
        ).status_code
        == 422
    )


def test_preferences_restore_and_respect_explicit_launch_values(
    db: Session, tmp_path: Path
) -> None:
    settings = Settings(data_dir=tmp_path, _env_file=None)
    config = RailSetupConfig(
        graph_root=str(tmp_path / "graphs"),
        pbf_path=str(tmp_path / "rail.osm.pbf"),
        java_home="",
        jar_path="",
    )
    save_rail_preferences(db, settings, config, set())
    assert settings.rail_enabled and settings.rail_sidecar_managed
    restored = Settings(data_dir=tmp_path, _env_file=None)
    restore_rail_preferences(db, restored)
    assert restored.rail_enabled
    assert restored.rail_graph_root == tmp_path / "graphs"
    locked = Settings(
        data_dir=tmp_path,
        rail_enabled=False,
        rail_graph_version="explicit",
        _env_file=None,
    )
    restore_rail_preferences(db, locked)
    assert not locked.rail_enabled and locked.rail_graph_version == "explicit"
    with pytest.raises(RailSidecarError, match="启动"):
        save_rail_preferences(db, locked, config, {"rail_enabled"})
    db.add_all(
        [
            AppMeta(key="setup.progress", value="invalid"),
            AppMeta(key="setup.rail.unknown", value="true"),
            AppMeta(key="setup.rail.rail_java_opts", value=json.dumps("bad")),
        ]
    )
    db.commit()
    assert get_progress(db)[0].step == "check"
    restore_rail_preferences(db, restored)
    assert restored.rail_java_opts == "-Xms256m -Xmx2500m"


def test_service_start_is_nonblocking_persistent_and_distinct_from_index_ready(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, _env_file=None)
    controller = RailServiceController(settings)
    started, release = threading.Event(), threading.Event()

    def start(*, cancel_event: threading.Event) -> None:
        started.set()
        assert release.wait(5) or cancel_event.is_set()

    monkeypatch.setattr(controller._supervisor, "start", start)
    monkeypatch.setattr(controller, "refresh", controller.snapshot)
    monkeypatch.setattr(client.app.state, "rail_service", controller)
    monkeypatch.setattr("app.api.onboarding.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.rail_data.get_settings", lambda: settings)
    config = current_rail_config(settings).model_dump()
    try:
        response = client.post("/api/v1/setup/rail/start", json=config)
        assert response.status_code == 202 and response.json()["status"] == "starting"
        assert started.wait(1)
        assert client.get("/healthz").status_code == 200
        assert client.post("/api/v1/setup/rail/start", json=config).status_code == 409
        assert (
            db.scalar(
                select(AppMeta.value).where(AppMeta.key == "setup.rail.rail_enabled")
            )
            == "true"
        )
    finally:
        release.set()
        assert controller._worker is not None
        controller._worker.join(timeout=2)
    state = client.get("/api/v1/setup").json()
    assert state["service"]["status"] == "ready"
    assert state["rail"]["status"] != "ready"
    assert (
        client.post(
            "/api/v1/setup/rail/start", json={**config, "graph_version": "other"}
        ).status_code
        == 409
    )
    controller.stop()
    with pytest.raises(RailSidecarError):
        controller.start()


def test_service_failure_can_be_retried_and_launch_overrides_are_enforced(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path, _env_file=None)
    controller = RailServiceController(settings)

    def failed(*, cancel_event: threading.Event) -> None:
        raise RailSidecarError("rail_pbf_checksum_mismatch", "文件身份不一致")

    monkeypatch.setattr(controller._supervisor, "start", failed)
    monkeypatch.setattr(client.app.state, "rail_service", controller)
    monkeypatch.setattr("app.api.onboarding.get_settings", lambda: settings)
    config = current_rail_config(settings).model_dump()
    client.post("/api/v1/setup/rail/start", json=config)
    assert controller._worker is not None
    controller._worker.join(timeout=2)
    assert controller.snapshot().error_code == "rail_pbf_checksum_mismatch"
    monkeypatch.setattr(controller._supervisor, "start", lambda **kwargs: None)
    client.post("/api/v1/setup/rail/start", json=config)
    controller._worker.join(timeout=2)
    assert controller.snapshot().status == "ready"
    controller.stop()
    locked = Settings(data_dir=tmp_path, rail_enabled=False, _env_file=None)
    controller = RailServiceController(locked)
    monkeypatch.setattr(client.app.state, "rail_service", controller)
    monkeypatch.setattr("app.api.onboarding.get_settings", lambda: locked)
    assert (
        client.post(
            "/api/v1/setup/rail/start", json=current_rail_config(locked).model_dump()
        ).json()["error"]["code"]
        == "rail_launch_override"
    )
    controller.stop()


def test_service_monitor_detects_a_lost_external_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr("app.rail.supervisor.fetch_sidecar_info", lambda *args: _info())
    monkeypatch.setattr("app.rail.service.fetch_sidecar_info", lambda *args: _info())
    controller = RailServiceController(settings)
    controller.start()
    assert controller._worker is not None
    controller._worker.join(timeout=2)
    assert controller.refresh().status == "ready"
    assert not controller._supervisor.owns_process

    def unavailable(*args: object) -> None:
        raise RailSidecarError("rail_sidecar_unavailable", "铁路服务已断开")

    monkeypatch.setattr("app.rail.service.fetch_sidecar_info", unavailable)
    assert controller.refresh().status == "failed"
    assert controller.snapshot().message == "铁路服务已断开"
    controller.stop()


def test_supervisor_cancelled_start_never_spawns_a_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.rail.supervisor import RailSidecarSupervisor

    def unavailable(*args: object) -> None:
        raise RailSidecarError("rail_sidecar_unavailable", "not running")

    monkeypatch.setattr("app.rail.supervisor.fetch_sidecar_info", unavailable)
    monkeypatch.setattr(
        "app.rail.supervisor._spawn_sidecar",
        lambda *args, **kwargs: pytest.fail("cancelled startup must not launch Java"),
    )
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RailSidecarError, match="取消"):
        RailSidecarSupervisor(_settings(tmp_path)).start(cancel_event=cancel)
