from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.core.config import Settings
from app.rail.sidecar import RailSidecarError, RailSidecarInfo
from app.rail.supervisor import RailSidecarSupervisor, _sidecar_runtime


def _settings(tmp_path: Path) -> Settings:
    graph_root = tmp_path / "graphs"
    graph_path = graph_root / "graph-v1"
    graph_path.mkdir(parents=True)
    pbf_path = tmp_path / "rail.osm.pbf"
    pbf_path.write_bytes(b"rail-pbf")
    import hashlib

    metadata = {
        "graph_version": "graph-v1",
        "pbf_filename": pbf_path.name,
        "pbf_sha256": hashlib.sha256(pbf_path.read_bytes()).hexdigest(),
        "profile_version": "profile-v1",
        "openrailrouting_commit": "commit-v1",
        "graphhopper_version": "graphhopper-v1",
        "source_timestamp": "2026-08-31T00:00:00Z",
        "extract_region": "fixture",
        "license": "ODbL-1.0",
    }
    (graph_path / "transit2fog-graph.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    jar_path = tmp_path / "openrailrouting.jar"
    jar_path.touch()
    config_path = tmp_path / "config.yml"
    config_path.write_text("server: {}\n", encoding="utf-8")
    java_home = tmp_path / "jdk"
    java_path = java_home / "bin" / ("java.exe" if os.name == "nt" else "java")
    java_path.parent.mkdir(parents=True)
    java_path.touch()
    return Settings(
        data_dir=tmp_path,
        rail_enabled=True,
        rail_sidecar_managed=True,
        rail_graph_version="graph-v1",
        rail_graph_root=graph_root,
        rail_pbf_path=pbf_path,
        rail_sidecar_jar=jar_path,
        rail_sidecar_config=config_path,
        rail_java_home=java_home,
        rail_sidecar_startup_seconds=1,
        _env_file=None,
    )


def _info(*, graph_version: str = "graph-v1") -> RailSidecarInfo:
    import hashlib

    return RailSidecarInfo(
        version="test",
        profiles=frozenset({"china_high_speed", "china_emu", "china_conventional"}),
        bbox=(100, 20, 130, 40),
        import_date=None,
        data_date=None,
        graph_version=graph_version,
        pbf_sha256=hashlib.sha256(b"rail-pbf").hexdigest(),
        profile_version="profile-v1",
        openrailrouting_commit="commit-v1",
    )


def test_managed_sidecar_command_is_loopback_and_identity_bound(
    tmp_path: Path,
) -> None:
    runtime = _sidecar_runtime(_settings(tmp_path))

    assert "-Dtransit2fog.graph.version=graph-v1" in runtime.command
    assert "-Dtransit2fog.pbf.sha256=" + _info().pbf_sha256 in runtime.command
    assert "-Ddw.server.application_connectors[0].port=8989" in runtime.command
    assert runtime.command[-2:] == ["serve", str(tmp_path / "config.yml")]


def test_custom_java_path_is_one_argument_without_shell_interpretation(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    java_home = tmp_path / "custom Java & tools;"
    executable = java_home / "bin" / ("java.exe" if os.name == "nt" else "java")
    executable.parent.mkdir(parents=True)
    executable.touch()
    settings.rail_java_home = java_home

    runtime = _sidecar_runtime(settings)

    assert runtime.command[0] == str(executable)
    assert runtime.command[-3] == str(settings.resolved_rail_sidecar_jar)


def test_supervisor_reuses_matching_external_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.rail.supervisor.fetch_sidecar_info", lambda *args: _info())
    monkeypatch.setattr(
        "app.rail.supervisor._spawn_sidecar",
        lambda *args, **kwargs: pytest.fail("must not spawn an existing sidecar"),
    )
    settings = _settings(tmp_path)
    settings.resolved_rail_sidecar_jar.unlink()
    supervisor = RailSidecarSupervisor(settings)

    supervisor.start()
    supervisor.stop()

    assert not supervisor.owns_process


def test_supervisor_starts_and_stops_owned_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = 0

    def probe(*args: object) -> RailSidecarInfo:
        nonlocal calls
        del args
        calls += 1
        if calls == 1:
            raise RailSidecarError("rail_sidecar_unavailable", "not running")
        return _info()

    class FakeProcess:
        returncode: int | None = None
        terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout: float) -> int:
            del timeout
            assert self.returncode is not None
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9

    process = FakeProcess()
    monkeypatch.setattr("app.rail.supervisor.fetch_sidecar_info", probe)
    monkeypatch.setattr(
        "app.rail.supervisor._spawn_sidecar", lambda *args, **kwargs: process
    )
    supervisor = RailSidecarSupervisor(_settings(tmp_path))

    supervisor.start()
    assert supervisor.owns_process
    supervisor.stop()

    assert process.terminated
    assert not supervisor.owns_process


def test_supervisor_rejects_existing_sidecar_with_wrong_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "app.rail.supervisor.fetch_sidecar_info",
        lambda *args: _info(graph_version="other-graph"),
    )

    with pytest.raises(RailSidecarError) as captured:
        RailSidecarSupervisor(_settings(tmp_path)).start()

    assert captured.value.code == "rail_sidecar_identity_mismatch"
