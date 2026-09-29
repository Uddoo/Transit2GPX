"""Pinned public data catalogue and restart-safe, on-demand city installation."""

from __future__ import annotations

import shutil
import tempfile
import threading
import urllib.error
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.resources import resource_path
from app.importers.city_pack import (
    MAX_ARCHIVE,
    CityPackError,
    PackManifest,
    install_city_pack,
    read_city_pack,
)
from app.rail.components import ComponentError, download_archive

DATA_RELEASE = "metro-data-2025-06-r1"
RELEASE_URL = f"https://github.com/Uddoo/transit2fog/releases/tag/{DATA_RELEASE}"
ASSET_PREFIX = f"https://github.com/Uddoo/transit2fog/releases/download/{DATA_RELEASE}/"
BUSY_STATES = {"downloading", "installing"}


class CatalogEntry(BaseModel):
    city_code: str = Field(min_length=1, max_length=100)
    city_name: str
    city_name_en: str | None = None
    file: str = Field(pattern=r"^[A-Za-z0-9._-]+\.t2fcity$")
    url: str
    size: int = Field(gt=0, le=MAX_ARCHIVE)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stations: int = Field(ge=0)
    ready_variants: int = Field(ge=0)
    blocked_variants: int = Field(ge=0)
    manifest: PackManifest

    @model_validator(mode="after")
    def validate_identity(self) -> CatalogEntry:
        if self.url != ASSET_PREFIX + self.file:
            raise ValueError("数据包地址不属于固定的数据发布版本。")
        if (self.city_code, self.city_name) != (
            self.manifest.city_code,
            self.manifest.city_name,
        ):
            raise ValueError("目录条目与城市清单不一致。")
        return self


class CityCatalog(BaseModel):
    format: Literal["transit2fog-city-catalog-v1"]
    release_tag: Literal["metro-data-2025-06-r1"]
    data_snapshot: str
    license: str
    scope_note: str
    packages: list[CatalogEntry] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique_cities(self) -> CityCatalog:
        if len({item.city_code for item in self.packages}) != len(self.packages):
            raise ValueError("目录包含重复城市编码。")
        return self


@lru_cache
def load_catalog() -> CityCatalog:
    return CityCatalog.model_validate_json(
        resource_path("city-data", "catalog.json").read_bytes()
    )


class CityDownloadState(BaseModel):
    status: Literal["idle", "downloading", "installing", "ready", "failed"] = "idle"
    city_code: str | None = None
    city_name: str | None = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    message: str | None = None
    dataset_id: int | None = None


class CityCatalogInstaller:
    def __init__(self, settings: Settings) -> None:
        self._root = settings.data_dir / "city-packs"
        self._receipt = self._root / "download-state.json"
        self._state = CityDownloadState()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        try:
            previous = CityDownloadState.model_validate_json(self._receipt.read_bytes())
            if previous.status in BUSY_STATES | {"failed"}:
                previous.status = "failed"
                previous.message = (
                    "上次准备未完成，点击重试可继续下载；已有城市仍可使用。"
                )
                self._state = previous
        except (OSError, ValueError):
            pass

    def snapshot(self) -> CityDownloadState:
        with self._lock:
            return self._state.model_copy()

    def _persist(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self._receipt.with_suffix(".tmp")
        temporary.write_text(self._state.model_dump_json(), encoding="utf-8")
        temporary.replace(self._receipt)

    def start(self, city_code: str) -> CityDownloadState:
        entry = next(
            (item for item in load_catalog().packages if item.city_code == city_code),
            None,
        )
        if entry is None:
            raise CityPackError("目录中没有这个城市，请重新选择。")
        with self._lock:
            if self._cancel.is_set():
                raise CityPackError("应用正在关闭，请重新打开后继续。")
            if self._state.status in BUSY_STATES:
                if self._state.city_code != city_code:
                    raise CityPackError("请等待当前城市安装完成，再选择其他城市。")
                return self.snapshot()
            self._state = CityDownloadState(
                status="downloading",
                city_code=entry.city_code,
                city_name=entry.city_name,
                total_bytes=entry.size,
                message="正在下载城市数据…",
            )
            try:
                self._persist()
            except OSError:
                self._state.status = "failed"
                self._state.message = (
                    "无法保存下载任务，请检查数据目录的可用空间和写入权限。"
                )
                raise
            self._worker = threading.Thread(
                target=self._run, args=(entry,), name="city-data-download", daemon=True
            )
            self._worker.start()
            return self.snapshot()

    def _progress(self, size: int) -> None:
        with self._lock:
            self._state.downloaded_bytes = size

    def _run(self, entry: CatalogEntry) -> None:
        try:
            archive = download_archive(
                entry, self._root / "downloads", self._progress, self._cancel
            )
            if self._cancel.is_set():
                raise CityPackError("准备已暂停，请重新打开应用后重试。")
            preview, _ = read_city_pack(archive)
            if preview.manifest != entry.manifest or preview.package_id != entry.sha256:
                raise CityPackError("数据包与发布目录不一致，请从数据发布页重新获取。")
            target = self._root / f"{entry.sha256}.t2fcity"
            with tempfile.TemporaryDirectory(
                prefix=".download-", dir=self._root
            ) as staging:
                temporary = Path(staging) / "city.t2fcity"
                shutil.copyfile(archive, temporary)
                temporary.replace(target)
            with self._lock:
                self._state.status = "installing"
                self._state.message = "校验通过，正在安装城市数据…"
            from app.db.session import SessionLocal

            with SessionLocal() as db:
                dataset_id = install_city_pack(db, target, entry.sha256)
            with self._lock:
                self._state.status = "ready"
                self._state.dataset_id = dataset_id
                self._state.message = f"{entry.city_name}已就绪，可以开始记录行程。"
                self._persist()
        except Exception as error:
            if isinstance(error, urllib.error.HTTPError):
                message = "下载地址暂不可用，请稍后重试，或从数据发布页下载后导入。"
            elif isinstance(error, (CityPackError, ComponentError)):
                message = str(error)
            elif isinstance(error, IntegrityError):
                message = "数据安装未完成，已有城市已保留。请重新获取城市包。"
            else:
                message = "下载未完成，请检查网络和可用空间后重试；也可导入本地城市包。"
            with self._lock:
                self._state.status = "failed"
                self._state.message = message
                with suppress(OSError):
                    self._persist()

    def stop(self) -> None:
        self._cancel.set()
        if self._worker:
            self._worker.join(timeout=16)
