from __future__ import annotations

import hashlib
import io
import os
import stat
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.rail import components
from app.rail.components import (
    ComponentError,
    ComponentInstaller,
    RuntimeManifest,
    download_archive,
    extract_runtime,
    installation_lock,
    installed_runtime,
    platform_tag,
    runtime_directory,
)
from app.rail.supervisor import _java_executable


def payload() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("openrailrouting.jar", b"fixture jar")
        archive.writestr(
            "java/bin/java.exe" if os.name == "nt" else "java/bin/java", b"fixture java"
        )
        archive.writestr("java/legal/LICENSE", b"fixture license")
    return stream.getvalue()


def manifest_for(data: bytes) -> RuntimeManifest:
    return RuntimeManifest(
        platform=platform_tag(),
        url="https://example.org/runtime.zip",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        unpacked_size=4096,
        java_version="21",
        sidecar_commit="fixture",
    )


class Response(io.BytesIO):
    def __init__(
        self, data: bytes, status: int = 200, headers: dict[str, str] | None = None
    ):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


@pytest.mark.parametrize("range_supported", [True, False])
def test_resume_or_restart_and_verified_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, range_supported: bool
) -> None:
    data = payload()
    manifest = manifest_for(data)
    (tmp_path / f"{manifest.sha256}.part").write_bytes(data[:21])
    requests = []

    def open_download(request, **kwargs):
        requests.append(request)
        assert request.get_header("Range") == "bytes=21-"
        return (
            Response(
                data[21:],
                206,
                {"Content-Range": f"bytes 21-{len(data) - 1}/{len(data)}"},
            )
            if range_supported
            else Response(data)
        )

    monkeypatch.setattr(
        components.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=open_download),
    )
    progress = []
    archive = download_archive(manifest, tmp_path, progress.append, threading.Event())
    assert archive.read_bytes() == data and progress[-1] == len(data)
    assert (
        download_archive(manifest, tmp_path, progress.append, threading.Event())
        == archive
    )
    assert len(requests) == 1


def test_bad_checksum_never_installs_and_retry_can_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = payload()
    manifest = manifest_for(data)
    monkeypatch.setattr(
        components.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(
            open=lambda *args, **kwargs: Response(b"x" * len(data))
        ),
    )
    with pytest.raises(ComponentError, match="校验失败"):
        download_archive(manifest, tmp_path, lambda _: None, threading.Event())
    assert not list(tmp_path.glob("*.zip")) and not list(tmp_path.glob("*.part"))
    monkeypatch.setattr(
        components.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(data)),
    )
    assert download_archive(
        manifest, tmp_path, lambda _: None, threading.Event()
    ).is_file()


def test_truncated_download_keeps_partial_and_bad_range_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = payload()
    manifest = manifest_for(data)
    monkeypatch.setattr(
        components.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(data[:20])),
    )
    with pytest.raises(ComponentError, match="未完成"):
        download_archive(manifest, tmp_path, lambda _: None, threading.Event())
    assert (tmp_path / f"{manifest.sha256}.part").read_bytes() == data[:20]
    monkeypatch.setattr(
        components.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(
            open=lambda *args, **kwargs: Response(
                data[20:], 206, {"Content-Range": "bytes 0-1/2"}
            )
        ),
    )
    with pytest.raises(ComponentError, match="分段"):
        download_archive(manifest, tmp_path, lambda _: None, threading.Event())


@pytest.mark.parametrize(
    "name", ["../escape", "/escape", "java/../../escape", "C:/escape", "java\\escape"]
)
def test_archive_paths_cannot_escape(tmp_path: Path, name: str) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(name, "bad")
    if name == "java\\escape":
        # ZipInfo normalizes host separators while writing on Windows. Restore
        # the hostile name in both ZIP headers to exercise reader validation.
        archive.write_bytes(
            archive.read_bytes().replace(b"java/escape", b"java\\escape")
        )
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(ComponentError, match="路径"):
        extract_runtime(archive, target, 1000)
    assert not list(target.rglob("*"))


def test_symlink_and_unpacked_limit_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        entry = zipfile.ZipInfo("java/link")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        stream.writestr(entry, "../../escape")
    with pytest.raises(ComponentError):
        extract_runtime(archive, tmp_path / "target", 1000)
    with pytest.raises(ComponentError, match="大小"):
        extract_runtime(archive, tmp_path / "target", 1)


def test_install_is_atomic_retryable_and_uses_private_java(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = payload()
    manifest = manifest_for(data)
    monkeypatch.setattr(components, "load_manifest", lambda: manifest)
    monkeypatch.setattr(
        components.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(data)),
    )
    settings = Settings(data_dir=tmp_path, _env_file=None)
    installer = ComponentInstaller(settings)
    entered, release = threading.Event(), threading.Event()

    def verify(directory: Path) -> None:
        entered.set()
        assert installed_runtime(tmp_path) is None
        assert release.wait(3)
        raise ComponentError("fixture Java failure")

    monkeypatch.setattr(components, "verify_java", verify)
    assert installer.start().status == "downloading"
    assert entered.wait(3)
    worker = installer._worker
    assert installer.start().status == "installing"
    assert worker is installer._worker
    release.set()
    assert worker is not None
    worker.join(3)
    assert installer.snapshot().status == "failed"
    assert not runtime_directory(tmp_path, manifest).exists()
    monkeypatch.setattr(components, "verify_java", lambda _: None)
    installer.start()
    assert installer._worker is not None
    installer._worker.join(3)
    assert installer.snapshot().status == "ready"
    runtime = installed_runtime(tmp_path)
    assert runtime is not None
    assert _java_executable(settings).parent.parent == runtime / "java"
    assert settings.resolved_rail_sidecar_jar == runtime / "openrailrouting.jar"
    assert ComponentInstaller(settings).snapshot().status == "ready"
    marker = runtime / ".complete"
    marker.write_bytes(b"\xff\xfe")
    assert installed_runtime(tmp_path) is None
    assert ComponentInstaller(settings).snapshot().status == "idle"
    marker.write_text(manifest.sha256, encoding="ascii")
    explicit = tmp_path / "custom.jar"
    settings.rail_sidecar_jar = explicit
    assert settings.resolved_rail_sidecar_jar == explicit
    installer.stop()


def test_missing_manifest_and_https_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(components, "load_manifest", lambda: None)
    installer = ComponentInstaller(Settings(data_dir=tmp_path, _env_file=None))
    assert installer.snapshot().status == "unavailable"
    with pytest.raises(ComponentError, match="清单"):
        installer.start()
    with pytest.raises(ValueError):
        RuntimeManifest.model_validate(
            {
                **manifest_for(payload()).model_dump(),
                "url": "http://example.org/runtime.zip",
            }
        )
    with pytest.raises(ComponentError, match="不安全"):
        components.HTTPSRedirectHandler().redirect_request(
            None, None, 302, "", {}, "http://example.org/file"
        )


def test_install_lock_released(tmp_path: Path) -> None:
    lock = tmp_path / "install.lock"
    with (
        installation_lock(lock),
        pytest.raises(ComponentError, match="另一个"),
        installation_lock(lock),
    ):
        pytest.fail("concurrent install was allowed")
    with installation_lock(lock):
        pass


def test_component_api_keeps_other_routes_available(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = payload()
    monkeypatch.setattr(components, "load_manifest", lambda: manifest_for(data))
    started, release = threading.Event(), threading.Event()
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(data)

    def download(*args):
        started.set()
        assert release.wait(3)
        return archive

    monkeypatch.setattr(components, "download_archive", download)
    monkeypatch.setattr(components, "verify_java", lambda _: None)
    installer = ComponentInstaller(Settings(data_dir=tmp_path, _env_file=None))
    monkeypatch.setattr(client.app.state, "rail_components", installer)
    try:
        assert client.post("/api/v1/setup/rail/components").status_code == 422
        response = client.post("/api/v1/setup/rail/components", json={"install": True})
        assert response.status_code == 202
        assert started.wait(2)
        assert client.get("/healthz").status_code == 200
        assert (
            client.get("/api/v1/setup").json()["components"]["status"] == "downloading"
        )
        assert (
            client.post(
                "/api/v1/setup/rail/start", json={"graph_root": str(tmp_path)}
            ).status_code
            == 409
        )
    finally:
        release.set()
        installer.stop()
