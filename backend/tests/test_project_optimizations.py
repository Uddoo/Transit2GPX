from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event

import pytest
from factories import seed_linear_network
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppTask,
    DatasetVersion,
    ImportBatch,
    ImportRow,
    Journey,
    RailDatasetVersion,
)


def _csv(rows: int = 3) -> bytes:
    header = "journey_id,leg_no,city,line,start_station,end_station,traveled_at\n"
    return (
        header
        + "".join(
            f"batch-{index},1,上海,测试线,甲站,丙站,2026-08-20\n"
            for index in range(rows)
        )
    ).encode()


def test_pagination_search_facets_and_bounded_list_queries(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    upload = client.post(
        "/api/v1/import-batches", files={"file": ("large.csv", _csv(125))}
    )
    assert upload.status_code == 201
    batch_id = upload.json()["id"]
    assert (
        client.post(
            f"/api/v1/import-batches/{batch_id}/commit", json={"strategy": "all"}
        ).status_code
        == 200
    )
    oldest = db.scalar(select(Journey).order_by(Journey.id))
    assert oldest is not None
    oldest.note = "第一个旅程 100%_done"
    oldest.traveled_at = date(2020, 1, 1)
    db.commit()
    from app.db.session import engine

    selects: list[str] = []

    def count_queries(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count_queries)
    try:
        listing = client.get("/api/v1/journeys?limit=100").json()
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
    assert listing["total"] == 125
    assert len(listing["items"]) == 100
    assert len(selects) <= 10
    assert len(listing["items"][0]["legs"][0]["edge_ids"]) == 2

    second = client.get("/api/v1/journeys?summary=true&offset=100&limit=100").json()
    assert len(second["items"]) == 25
    assert "edge_ids" not in second["items"][0]["legs"][0]
    for query, total in (
        ("甲站", 125),
        ("测试线", 125),
        ("第一个旅程", 1),
        ("100%_done", 1),
        ("不存在", 0),
    ):
        assert (
            client.get("/api/v1/journeys", params={"q": query}).json()["total"] == total
        )
    assert (
        client.get("/api/v1/journeys?traveled_to=2020-01-01").json()["items"][0]["id"]
        == oldest.id
    )
    facets = client.get("/api/v1/journeys/filters").json()
    assert facets["cities"][0]["id"] == network.city_id
    assert facets["lines"][0]["id"] == network.line_id


def test_csv_background_processing_is_responsive_and_can_pause_resume(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import csv_imports

    seed_linear_network(db)
    started, release = Event(), Event()
    original = csv_imports._resolve_row
    calls = 0

    def resolve(db: Session, row: ImportRow) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            started.set()
            assert release.wait(10)
        original(db, row)

    monkeypatch.setattr(csv_imports, "_resolve_row", resolve)
    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(
            client.post, "/api/v1/import-batches", files={"file": ("batch.csv", _csv())}
        )
        try:
            assert started.wait(5)
            batch_id = db.scalar(select(ImportBatch.id))
            # Another request still completes while the CSV resolver is blocked.
            health = pool.submit(client.get, "/healthz").result(timeout=2)
            assert health.status_code == 200
            status = client.get(f"/api/v1/import-batches/{batch_id}").json()
            assert (status["status"], status["processed_rows"]) == ("parsing", 1)
            assert (
                client.post(
                    f"/api/v1/import-batches/{batch_id}/commit",
                    json={"strategy": "resolved_only"},
                ).status_code
                == 409
            )
            assert (
                client.post(f"/api/v1/import-batches/{batch_id}/resume").status_code
                == 409
            )
            assert (
                client.post(f"/api/v1/import-batches/{batch_id}/cancel").json()[
                    "status"
                ]
                == "cancelled"
            )
        finally:
            release.set()
        assert upload.result(timeout=5).status_code == 201
    paused = client.get(f"/api/v1/import-batches/{batch_id}").json()
    assert paused["processed_rows"] == 1
    assert client.post(f"/api/v1/import-batches/{batch_id}/resume").status_code == 202
    completed = client.get(f"/api/v1/import-batches/{batch_id}").json()
    assert (
        completed["status"],
        completed["processed_rows"],
        completed["resolved_rows"],
    ) == ("ready_for_review", 3, 3)
    assert calls == 4  # only the interrupted row and remaining row are retried


def test_csv_failed_worker_preserves_completed_rows(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api import csv_imports

    seed_linear_network(db)
    original = csv_imports._resolve_row
    calls = 0

    def resolve(db: Session, row: ImportRow) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic interruption")
        original(db, row)

    monkeypatch.setattr(csv_imports, "_resolve_row", resolve)
    batch_id = client.post(
        "/api/v1/import-batches", files={"file": ("batch.csv", _csv())}
    ).json()["id"]
    failed = client.get(f"/api/v1/import-batches/{batch_id}").json()
    assert (failed["status"], failed["processed_rows"]) == ("failed", 1)
    assert failed["error_message"]
    client.post(f"/api/v1/import-batches/{batch_id}/resume")
    assert client.get(f"/api/v1/import-batches/{batch_id}").json()["resolved_rows"] == 3


def test_startup_marks_abandoned_imports_retryable_without_touching_ready_data(
    client: TestClient, db: Session, tmp_path: Path
) -> None:
    from app.importers.cptond import DatasetAudit, create_dataset_import
    from app.importers.recovery import recover_interrupted_imports

    network = seed_linear_network(db)
    interrupted = DatasetVersion(
        source_name="CPTOND",
        source_version="interrupted",
        captured_at="2025-06",
        license="test",
        source_url="https://example.test",
        checksum="interrupted",
        importer_schema_version="test",
        status="checking",
    )
    batch = ImportBatch(
        filename="interrupted.csv",
        encoding="utf-8",
        status="parsing",
        run_token="old-worker",
    )
    rail = RailDatasetVersion(
        source_name="OSM",
        source_url="https://example.test",
        source_timestamp="2026-08-20",
        pbf_checksum="rail-interrupted",
        extract_region="test",
        graph_version="interrupted",
        profile_version="test",
        openrailrouting_version="test",
        graphhopper_version="test",
        license="test",
        status="building",
    )
    db.add_all([interrupted, batch, rail])
    db.commit()
    recover_interrupted_imports(db)
    assert (
        client.get(f"/api/v1/data/imports/{interrupted.id}").json()["status"]
        == "failed"
    )
    assert client.get(f"/api/v1/import-batches/{batch.id}").json()["status"] == "failed"
    db.expire_all()
    assert db.get(DatasetVersion, network.dataset_id).status == "ready"
    assert db.get(ImportBatch, batch.id).run_token is None
    assert db.get(RailDatasetVersion, rail.id).status == "failed"
    assert (
        db.get(RailDatasetVersion, rail.id).quality_flags_json[0]["code"]
        == "rail_import_interrupted"
    )
    audit = DatasetAudit(
        root=tmp_path,
        bundles=(),
        checksum="interrupted",
        route_count=0,
        stop_count=0,
        source_format="cptond-v2",
        source_url="https://example.test",
        license="test",
        captured_at="2025-06",
        default_source_version="interrupted",
    )
    assert create_dataset_import(audit, "interrupted").should_run


def test_recovery_leaves_durable_imports_to_the_existing_executor(
    client: TestClient, db: Session
) -> None:
    from app.importers.recovery import recover_interrupted_imports

    network = seed_linear_network(db)
    dataset = db.get(DatasetVersion, network.dataset_id)
    assert dataset is not None
    dataset.status = "checking"
    db.add(
        AppTask(
            kind="cptond_import",
            resource_id=dataset.id,
            payload_json={},
            status="running",
        )
    )
    db.commit()
    recover_interrupted_imports(db)
    db.refresh(dataset)
    assert dataset.status == "checking"
