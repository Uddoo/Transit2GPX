from __future__ import annotations

import threading
import urllib.error
from pathlib import Path

import pytest
from factories import seed_linear_network
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import DatasetVersion
from app.importers.city_pack import export_city_pack
from app.services import city_catalog
from app.services.city_catalog import (
    ASSET_PREFIX,
    CatalogEntry,
    CityCatalogInstaller,
    CityDownloadState,
    load_catalog,
)


def make_entry(db: Session, tmp_path: Path) -> tuple[CatalogEntry, Path]:
    network = seed_linear_network(db)
    path = tmp_path / "test.t2fcity"
    preview = export_city_pack(db, network.city_id, path, "catalogue test fixture")
    return CatalogEntry(
        city_code=preview.manifest.city_code,
        city_name=preview.manifest.city_name,
        file=path.name,
        url=ASSET_PREFIX + path.name,
        size=path.stat().st_size,
        sha256=preview.package_id,
        stations=3,
        ready_variants=1,
        blocked_variants=0,
        manifest=preview.manifest,
    ), path


def test_published_catalogue_is_pinned_and_rejects_arbitrary_urls() -> None:
    catalog = load_catalog()
    assert len(catalog.packages) == 46
    assert catalog.data_snapshot == "2025-06"
    assert any(item.city_code == "1886" for item in catalog.packages)
    bad = catalog.packages[0].model_dump()
    bad["url"] = "http://127.0.0.1/private"
    with pytest.raises(ValueError, match="固定"):
        CatalogEntry.model_validate(bad)
    bad = catalog.model_dump()
    bad["packages"].append(bad["packages"][0])
    with pytest.raises(ValueError, match="重复"):
        type(catalog).model_validate(bad)


def test_download_runs_in_background_and_updates_inventory(
    client: TestClient, db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, path = make_entry(db, tmp_path)
    catalog = load_catalog().model_copy(update={"packages": [entry]})
    monkeypatch.setattr(city_catalog, "load_catalog", lambda: catalog)
    started, release = threading.Event(), threading.Event()

    def download(spec, cache, progress, cancel):
        started.set()
        progress(10)
        assert release.wait(3)
        progress(spec.size)
        return path

    monkeypatch.setattr(city_catalog, "download_archive", download)
    installer = CityCatalogInstaller(
        Settings(data_dir=tmp_path / "runtime", _env_file=None)
    )
    monkeypatch.setattr(client.app.state, "city_catalog", installer)
    try:
        response = client.post(
            "/api/v1/data/city-packs/download", json={"city_code": entry.city_code}
        )
        assert response.status_code == 202
        assert started.wait(2)
        worker = installer._worker
        assert client.get("/healthz").status_code == 200
        assert (
            client.get("/api/v1/data/city-packs/download").json()["status"]
            == "downloading"
        )
        assert (
            client.post(
                "/api/v1/data/city-packs/download", json={"city_code": entry.city_code}
            ).status_code
            == 202
        )
        assert worker is installer._worker
        assert (
            client.post(
                "/api/v1/data/city-packs/download", json={"city_code": "unknown"}
            ).status_code
            == 409
        )
        release.set()
        assert worker is not None
        worker.join(3)
        assert installer.snapshot().status == "ready"
        cities = client.get("/api/v1/cities").json()
        assert len(cities) == 1
        assert cities[0]["checksum"] == entry.sha256
        assert cities[0]["source_name"] == "CPTOND"
        assert (cities[0]["station_count"], cities[0]["direction_count"]) == (3, 1)
    finally:
        release.set()
        installer.stop()


def test_http_failure_can_retry_and_restart_reports_interruption(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, path = make_entry(db, tmp_path)
    catalog = load_catalog().model_copy(update={"packages": [entry]})
    monkeypatch.setattr(city_catalog, "load_catalog", lambda: catalog)
    settings = Settings(data_dir=tmp_path / "runtime", _env_file=None)
    installer = CityCatalogInstaller(settings)

    def fail(*args):
        raise urllib.error.HTTPError(entry.url, 404, "missing", {}, None)

    monkeypatch.setattr(city_catalog, "download_archive", fail)
    installer.start(entry.city_code)
    assert installer._worker is not None
    installer._worker.join(3)
    assert installer.snapshot().status == "failed"
    assert "发布页" in installer.snapshot().message
    recovered = CityCatalogInstaller(settings)
    assert recovered.snapshot().status == "failed"
    monkeypatch.setattr(city_catalog, "download_archive", lambda *args: path)
    recovered.start(entry.city_code)
    assert recovered._worker is not None
    recovered._worker.join(3)
    assert recovered.snapshot().status == "ready"
    assert CityCatalogInstaller(settings).snapshot().status == "idle"
    recovered.stop()
    with pytest.raises(ValueError, match="关闭"):
        recovered.start(entry.city_code)
    receipt = settings.data_dir / "city-packs" / "download-state.json"
    receipt.write_text(
        CityDownloadState(
            status="installing", city_code=entry.city_code
        ).model_dump_json()
    )
    assert CityCatalogInstaller(settings).snapshot().status == "failed"


def test_manifest_mismatch_does_not_install(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, path = make_entry(db, tmp_path)
    entry.manifest.source.version = "unexpected-version"
    monkeypatch.setattr(
        city_catalog,
        "load_catalog",
        lambda: load_catalog().model_copy(update={"packages": [entry]}),
    )
    monkeypatch.setattr(city_catalog, "download_archive", lambda *args: path)
    installer = CityCatalogInstaller(
        Settings(data_dir=tmp_path / "runtime", _env_file=None)
    )
    installer.start(entry.city_code)
    assert installer._worker is not None
    installer._worker.join(3)
    assert installer.snapshot().status == "failed"
    assert db.scalar(select(func.count()).select_from(DatasetVersion)) == 1


def test_city_inventory_keeps_both_sources(client: TestClient, db: Session) -> None:
    seed_linear_network(db, city_name="上海", city_code="021")
    seed_linear_network(db, suffix="second", city_name="杭州", city_code="0571")
    cities = client.get("/api/v1/cities").json()
    assert {item["city_code"] for item in cities} == {"021", "0571"}
    assert all(
        item["station_count"] == 3 and item["direction_count"] == 1 for item in cities
    )
