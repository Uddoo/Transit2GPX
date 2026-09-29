"""Version-pinned optional railway runtime; no changes to the system Java/PATH."""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.core.resources import resource_path

if TYPE_CHECKING:
    from app.core.config import Settings


class ComponentError(RuntimeError):
    pass


def platform_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos"}.get(
        platform.system(), platform.system().lower()
    )
    machine = platform.machine().lower()
    return f"{system}-{'x64' if machine in {'amd64', 'x86_64'} else machine}"


class RuntimeManifest(BaseModel):
    schema_version: Literal[1] = 1
    platform: str
    url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(gt=0, le=512 * 1024 * 1024)
    unpacked_size: int = Field(gt=0, le=1024 * 1024 * 1024)
    java_version: str
    sidecar_commit: str

    @field_validator("url")
    @classmethod
    def secure_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError("组件下载地址必须使用无凭据的 HTTPS")
        return value


def load_manifest() -> RuntimeManifest | None:
    path = resource_path("rail-routing", "components.json")
    if not path.is_file():
        return None
    manifest = RuntimeManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.platform != platform_tag():
        raise ComponentError("铁路组件与当前系统架构不匹配，请下载对应平台的安装包。")
    return manifest


def runtime_directory(data_dir: Path, manifest: RuntimeManifest) -> Path:
    return data_dir / "rail-routing" / "components" / manifest.sha256


def installed_runtime(data_dir: Path) -> Path | None:
    try:
        manifest = load_manifest()
    except (ValueError, OSError, ComponentError):
        return None
    if manifest is None:
        return None
    directory = runtime_directory(data_dir, manifest)
    java = directory / "java" / "bin" / ("java.exe" if os.name == "nt" else "java")
    marker = directory / ".complete"
    try:
        if (
            java.is_file()
            and (directory / "openrailrouting.jar").is_file()
            and marker.is_file()
            and marker.read_text(encoding="ascii") == manifest.sha256
        ):
            return directory
    except (OSError, UnicodeError):
        pass  # An incomplete/corrupt marker must not prevent metro startup.
    return None


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urlsplit(newurl).scheme != "https":
            raise ComponentError("组件下载被重定向到不安全的地址。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DownloadSpec(Protocol):
    url: str
    sha256: str
    size: int


def download_archive(
    manifest: DownloadSpec,
    cache: Path,
    progress: Callable[[int], None],
    cancel: threading.Event,
) -> Path:
    """Resume a bounded partial download, then verify before any extraction."""
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{manifest.sha256}.zip"
    if archive.is_file():
        if (
            archive.stat().st_size == manifest.size
            and sha256_file(archive) == manifest.sha256
        ):
            progress(manifest.size)
            return archive
        archive.unlink()
    partial = archive.with_suffix(".part")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > manifest.size:
        partial.unlink()
        offset = 0
    if offset < manifest.size:
        headers = {"User-Agent": "Transit2Fog", "Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(manifest.url, headers=headers)
        opener = urllib.request.build_opener(HTTPSRedirectHandler())
        with opener.open(request, timeout=10) as response:
            if response.status == 206:
                expected = f"bytes {offset}-{manifest.size - 1}/{manifest.size}"
                if response.headers.get("Content-Range") != expected:
                    raise ComponentError("下载服务器返回了错误的分段，请重试。")
            elif response.status == 200:
                offset = 0  # Server does not support Range; safely restart.
            else:
                raise ComponentError("下载服务器返回异常状态，请稍后重试。")
            with partial.open("ab" if offset else "wb") as stream:
                progress(offset)
                while block := response.read(256 * 1024):
                    if cancel.is_set():
                        raise ComponentError("下载已暂停，重新打开应用后可继续。")
                    offset += len(block)
                    if offset > manifest.size:
                        raise ComponentError("下载大小与发布清单不一致。")
                    stream.write(block)
                    progress(offset)
    if partial.stat().st_size != manifest.size:
        raise ComponentError("下载未完成，请重试以继续下载。")
    if sha256_file(partial) != manifest.sha256:
        partial.unlink()
        raise ComponentError("组件校验失败，文件已丢弃，请重新下载。")
    partial.replace(archive)
    return archive


def extract_runtime(archive: Path, target: Path, max_size: int) -> None:
    """Only regular files/directories; reject traversal, links and ZIP bombs."""
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 10000 or sum(item.file_size for item in entries) > max_size:
            raise ComponentError("组件解压大小超出发布清单。")
        seen: set[str] = set()
        for item in entries:
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (
                path.is_absolute()
                or not path.parts
                or any(part in {".", ".."} or ":" in part for part in path.parts)
                or "\\" in item.orig_filename
                or any(part.endswith((".", " ")) for part in path.parts)
                or stat.S_ISLNK(mode)
                or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}
                or item.filename.casefold() in seen
            ):
                raise ComponentError("组件包含不安全或重复的文件路径。")
            seen.add(item.filename.casefold())
            destination = target.joinpath(*path.parts)
            if not destination.resolve().is_relative_to(target.resolve()):
                raise ComponentError("组件路径超出安装目录。")
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open(item) as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            if os.name != "nt":
                destination.chmod(0o755 if mode & 0o111 else 0o644)


def verify_java(directory: Path) -> None:
    executable = (
        directory / "java" / "bin" / ("java.exe" if os.name == "nt" else "java")
    )
    if not (directory / "openrailrouting.jar").is_file():
        raise ComponentError("铁路组件缺少服务文件。")
    result = subprocess.run(
        [str(executable), "-version"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    match = re.search(r'version\s+"(\d+)', result.stdout + result.stderr)
    if result.returncode or match is None or int(match.group(1)) < 17:
        raise ComponentError("专用 Java 运行验证失败，请重新下载组件。")


@contextmanager
def installation_lock(path: Path) -> Iterator[None]:
    """OS-owned lock is released even when the application is interrupted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.write(b"\0")
        stream.flush()
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ComponentError(
                "另一个 Transit2Fog 正在准备组件，请稍后重试。"
            ) from error
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class ComponentState(BaseModel):
    status: Literal[
        "unavailable", "idle", "downloading", "installing", "ready", "failed"
    ] = "unavailable"
    downloaded_bytes: int = 0
    total_bytes: int = 0
    message: str | None = None
    jar_path: str | None = None
    java_home: str | None = None


class ComponentInstaller:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._manifest: RuntimeManifest | None = None
        self._state = ComponentState()
        try:
            self._manifest = load_manifest()
            if self._manifest:
                self._state = ComponentState(
                    status="idle", total_bytes=self._manifest.size
                )
                if directory := installed_runtime(settings.data_dir):
                    self._ready(directory)
        except (ValueError, OSError, ComponentError):
            self._state.message = "铁路组件清单不可用，请重新获取当前平台的安装包。"

    def snapshot(self) -> ComponentState:
        with self._lock:
            return self._state.model_copy()

    def start(self) -> ComponentState:
        with self._lock:
            if self._cancel.is_set():
                raise ComponentError("应用正在关闭，请重新打开后重试。")
            if self._manifest is None:
                raise ComponentError(
                    "此构建未提供在线组件清单，请使用发布版或手动配置。"
                )
            if self._state.status in {"downloading", "installing", "ready"}:
                return self.snapshot()
            self._state.status = "downloading"
            self._state.message = "正在下载铁路引擎和专用 Java，可稍后回来查看。"
            self._worker = threading.Thread(
                target=self._run, name="rail-components", daemon=True
            )
            self._worker.start()
            return self.snapshot()

    def _ready(self, directory: Path) -> None:
        self._state.status = "ready"
        self._state.downloaded_bytes = self._state.total_bytes
        self._state.message = "铁路组件已就绪；继续配置铁路图和 PBF 后即可启动。"
        self._state.jar_path = str(directory / "openrailrouting.jar")
        self._state.java_home = str(directory / "java")

    def _progress(self, size: int) -> None:
        with self._lock:
            self._state.downloaded_bytes = size

    def _run(self) -> None:
        assert self._manifest is not None
        manifest = self._manifest
        parent = self._settings.data_dir / "rail-routing" / "components"
        try:
            with installation_lock(parent / ".install.lock"):
                directory = runtime_directory(self._settings.data_dir, manifest)
                if installed_runtime(self._settings.data_dir):
                    with self._lock:
                        self._ready(directory)
                    return
                archive = download_archive(
                    manifest, parent / "downloads", self._progress, self._cancel
                )
                with self._lock:
                    self._state.status = "installing"
                    self._state.message = "下载校验通过，正在安装并验证 Java…"
                with tempfile.TemporaryDirectory(
                    prefix=".staging-", dir=parent
                ) as staging:
                    staged = Path(staging) / "runtime"
                    staged.mkdir()
                    extract_runtime(archive, staged, manifest.unpacked_size)
                    verify_java(staged)
                    if self._cancel.is_set():
                        raise ComponentError("安装已暂停，请重新打开应用后重试。")
                    (staged / ".complete").write_text(manifest.sha256, encoding="ascii")
                    if directory.exists():
                        # Never overwrite a possibly in-use installation. Preserve it.
                        directory.rename(
                            parent
                            / f".incomplete-{manifest.sha256}-{os.urandom(4).hex()}"
                        )
                    staged.rename(directory)
                with self._lock:
                    self._ready(directory)
        except Exception as error:
            with self._lock:
                self._state.status = "failed"
                self._state.message = (
                    str(error)
                    if isinstance(error, ComponentError)
                    else "组件准备失败，请检查网络和可用空间后重试；已下载部分会保留。"
                )

    def stop(self) -> None:
        self._cancel.set()
        if self._worker:
            self._worker.join(timeout=16)
