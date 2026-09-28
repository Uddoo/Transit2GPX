from __future__ import annotations

import hashlib
import logging
import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from app.core.config import Settings
from app.rail.importer import (
    RailImportError,
    load_graph_metadata,
    resolve_graph_path,
)
from app.rail.sidecar import (
    EXPECTED_RAIL_PROFILES,
    RailSidecarError,
    RailSidecarInfo,
    fetch_sidecar_info,
    validate_loopback_url,
)

logger = logging.getLogger(__name__)
_WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200


class RailSidecarSupervisor:
    """Start and stop an identity-checked loopback railway sidecar."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._process: subprocess.Popen[bytes] | None = None
        self._log_stream: BinaryIO | None = None
        self._owns_process = False

    @property
    def owns_process(self) -> bool:
        return self._owns_process

    @property
    def exited(self) -> bool:
        return (
            self._owns_process
            and self._process is not None
            and self._process.poll() is not None
        )

    def start(self, *, cancel_event: threading.Event | None = None) -> None:
        _managed_sidecar_port(self._settings)
        graph_path, metadata = _graph_runtime(self._settings)
        existing = _probe_sidecar(self._settings)
        if existing is not None:
            _verify_identity(existing, metadata)
            logger.info("Using an existing railway sidecar on loopback")
            return
        runtime = _sidecar_runtime(
            self._settings, graph_path=graph_path, metadata=metadata
        )

        if cancel_event is not None and cancel_event.is_set():
            raise RailSidecarError("rail_start_cancelled", "铁路服务启动已取消。")
        log_dir = self._settings.data_dir.resolve() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_stream = (log_dir / "rail-sidecar.log").open("ab", buffering=0)
        self._process = _spawn_sidecar(
            runtime.command,
            cwd=runtime.config_path.parent,
            log_stream=self._log_stream,
        )
        self._owns_process = True
        deadline = time.monotonic() + self._settings.rail_sidecar_startup_seconds
        last_error: RailSidecarError | None = None
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                self.stop()
                raise RailSidecarError("rail_start_cancelled", "铁路服务启动已取消。")
            if self._process.poll() is not None:
                self.stop()
                raise RailSidecarError(
                    "rail_sidecar_start_failed",
                    "铁路路径服务启动失败；请检查 rail-sidecar.log。",
                )
            try:
                info = fetch_sidecar_info(
                    self._settings.rail_sidecar_url,
                    min(self._settings.rail_sidecar_timeout_seconds, 1.0),
                )
                _verify_identity(info, runtime.metadata)
                logger.info("Managed railway sidecar is ready")
                return
            except RailSidecarError as error:
                last_error = error
                if error.code not in {"rail_sidecar_unavailable"}:
                    self.stop()
                    raise
                time.sleep(0.25)
        self.stop()
        raise RailSidecarError(
            "rail_sidecar_start_timeout",
            "铁路路径服务未在限定时间内就绪。",
        ) from last_error

    def stop(self) -> None:
        process = self._process
        if self._owns_process and process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._process = None
        self._owns_process = False
        if self._log_stream is not None:
            self._log_stream.close()
            self._log_stream = None


def _spawn_sidecar(
    command: list[str], *, cwd: Path, log_stream: BinaryIO
) -> subprocess.Popen[bytes]:
    if os.name == "nt":
        return subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            creationflags=_WINDOWS_CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


class _SidecarRuntime:
    def __init__(
        self,
        *,
        command: list[str],
        config_path: Path,
        metadata: dict[str, Any],
    ) -> None:
        self.command = command
        self.config_path = config_path
        self.metadata = metadata


def _graph_runtime(settings: Settings) -> tuple[Path, dict[str, Any]]:
    if not settings.rail_graph_version:
        raise RailSidecarError(
            "rail_graph_not_configured", "托管铁路服务需要指定图版本。"
        )
    try:
        return (
            resolve_graph_path(
                settings.resolved_rail_graph_root, settings.rail_graph_version
            ),
            load_graph_metadata(
                settings.resolved_rail_graph_root, settings.rail_graph_version
            ),
        )
    except RailImportError as error:
        raise RailSidecarError("rail_graph_invalid", str(error)) from error


def _managed_sidecar_port(settings: Settings) -> int:
    safe_url = validate_loopback_url(settings.rail_sidecar_url)
    parsed_url = urlsplit(safe_url)
    if parsed_url.path not in {"", "/"} or parsed_url.port is None:
        raise RailSidecarError(
            "rail_sidecar_url_invalid",
            "托管铁路服务地址必须是带端口的 loopback 根地址。",
        )
    return parsed_url.port


def _sidecar_runtime(
    settings: Settings,
    *,
    graph_path: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> _SidecarRuntime:
    application_port = _managed_sidecar_port(settings)
    if graph_path is None or metadata is None:
        graph_path, metadata = _graph_runtime(settings)

    jar_path = settings.resolved_rail_sidecar_jar
    config_path = settings.resolved_rail_sidecar_config
    if not jar_path.is_file():
        raise RailSidecarError(
            "rail_sidecar_jar_missing", "铁路路径服务 JAR 尚未安装。"
        )
    if not config_path.is_file():
        raise RailSidecarError(
            "rail_sidecar_config_missing", "铁路路径服务配置尚未安装。"
        )
    pbf_path = _resolve_pbf_path(settings, metadata)
    expected_checksum = str(metadata.get("pbf_sha256", ""))
    if _sha256_file(pbf_path) != expected_checksum:
        raise RailSidecarError(
            "rail_pbf_checksum_mismatch", "铁路 PBF 与图版本身份不一致。"
        )
    java = _java_executable(settings)
    identity = {
        key: str(metadata[key])
        for key in (
            "graph_version",
            "pbf_sha256",
            "profile_version",
            "openrailrouting_commit",
        )
    }
    command = [
        str(java),
        *shlex.split(settings.rail_java_opts),
        *(
            f"-Dtransit2fog.{key.replace('_', '.')}={value}"
            for key, value in identity.items()
        ),
        *(
            f"-Dmetro2fog.{key.replace('_', '.')}={value}"
            for key, value in identity.items()
        ),
        f"-Ddw.graphhopper.datareader.file={pbf_path}",
        f"-Ddw.graphhopper.graph.location={graph_path}",
        f"-Ddw.server.application_connectors[0].port={application_port}",
        f"-Ddw.server.admin_connectors[0].port={settings.rail_sidecar_admin_port}",
        "-jar",
        str(jar_path),
        "serve",
        str(config_path),
    ]
    return _SidecarRuntime(
        command=command,
        config_path=config_path,
        metadata=metadata,
    )


def _probe_sidecar(settings: Settings) -> RailSidecarInfo | None:
    try:
        return fetch_sidecar_info(
            settings.rail_sidecar_url,
            min(settings.rail_sidecar_timeout_seconds, 0.5),
        )
    except RailSidecarError as error:
        if error.code == "rail_sidecar_unavailable":
            return None
        raise


def _verify_identity(info: RailSidecarInfo, metadata: dict[str, Any]) -> None:
    expected = (
        str(metadata.get("graph_version", "")),
        str(metadata.get("pbf_sha256", "")),
        str(metadata.get("profile_version", "")),
        str(metadata.get("openrailrouting_commit", "")),
    )
    actual = (
        info.graph_version,
        info.pbf_sha256,
        info.profile_version,
        info.openrailrouting_commit,
    )
    if actual != expected or not EXPECTED_RAIL_PROFILES.issubset(info.profiles):
        raise RailSidecarError(
            "rail_sidecar_identity_mismatch",
            "运行中的铁路路径服务与 active 图身份不一致。",
        )


def _resolve_pbf_path(settings: Settings, metadata: dict[str, Any]) -> Path:
    if settings.rail_pbf_path:
        candidates = [settings.rail_pbf_path.resolve()]
    else:
        filename = metadata.get("pbf_filename")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
        ):
            raise RailSidecarError(
                "rail_pbf_missing", "铁路图元数据没有可定位的 PBF 文件名。"
            )
        work_roots = {
            settings.data_dir.resolve() / "rail-routing",
            settings.resolved_rail_graph_root.parent,
        }
        candidates = []
        for work_root in work_roots:
            candidates.append(work_root / "pbf" / filename)
            regions = work_root / "regions"
            if regions.is_dir():
                candidates.extend(regions.glob(f"*/{filename}"))
    existing = list(
        dict.fromkeys(path.resolve() for path in candidates if path.is_file())
    )
    if len(existing) != 1:
        raise RailSidecarError(
            "rail_pbf_missing",
            "无法唯一定位铁路图对应的 PBF；请设置 TRANSIT2FOG_RAIL_PBF_PATH。",
        )
    return existing[0]


def _java_executable(settings: Settings) -> Path:
    java_home = settings.rail_java_home
    if java_home is None and os.environ.get("RAIL_JAVA_HOME"):
        java_home = Path(os.environ["RAIL_JAVA_HOME"])
    executable_name = "java.exe" if os.name == "nt" else "java"
    if java_home is not None:
        executable = java_home.resolve() / "bin" / executable_name
        if executable.is_file():
            return executable
        raise RailSidecarError(
            "rail_java_missing", "指定的铁路 Java 目录不包含可执行文件。"
        )
    portable = (
        settings.data_dir.resolve()
        / "rail-routing"
        / "tools"
        / "temurin-21"
        / "bin"
        / executable_name
    )
    if portable.is_file():
        return portable
    discovered = shutil.which("java")
    if discovered:
        return Path(discovered)
    raise RailSidecarError("rail_java_missing", "铁路路径服务需要 Java 17 或更高版本。")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
