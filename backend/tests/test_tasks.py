from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from factories import seed_linear_network
from sqlalchemy.orm import Session

from app.db.models import AppTask, City, DatasetVersion, RailDatasetVersion


def test_persistent_executor_recovers_running_task_after_restart(db: Session) -> None:
    from app.db.session import SessionLocal
    from app.tasks.executor import PersistentTaskExecutor

    task = AppTask(
        kind="test_noop",
        resource_id=42,
        payload_json={"value": "persisted"},
        status="running",
        attempts=0,
    )
    db.add(task)
    db.commit()
    task_id = task.id
    completed = threading.Event()

    def dispatch(kind: str, resource_id: int, payload: dict[str, object]) -> None:
        assert kind == "test_noop"
        assert resource_id == 42
        assert payload == {"value": "persisted"}
        completed.set()

    executor = PersistentTaskExecutor(SessionLocal, dispatch)
    executor.start()
    try:
        assert completed.wait(timeout=2)
        with SessionLocal() as verification:
            for _ in range(100):
                recovered = verification.get(AppTask, task_id)
                if recovered is not None and recovered.status == "succeeded":
                    break
                verification.expire_all()
                time.sleep(0.01)
            else:
                raise AssertionError("persistent task did not finish")
            assert recovered is not None
            assert recovered.status == "succeeded"
            assert recovered.attempts == 1
            assert recovered.started_at is not None
            assert recovered.completed_at is not None
            assert recovered.error_type is None
    finally:
        executor.stop()


def test_persistent_executor_can_restart_same_instance(db: Session) -> None:
    from app.db.session import SessionLocal
    from app.tasks.executor import PersistentTaskExecutor

    completed = threading.Event()

    def dispatch(kind: str, resource_id: int, payload: dict[str, object]) -> None:
        del kind, resource_id, payload
        completed.set()

    executor = PersistentTaskExecutor(SessionLocal, dispatch)
    executor.start()
    executor.stop()
    executor.start()
    try:
        task = executor.enqueue(kind="test_restart", resource_id=1, payload={})
        assert completed.wait(timeout=2)
        with SessionLocal() as verification:
            for _ in range(100):
                recovered = verification.get(AppTask, task.id)
                if recovered is not None and recovered.status == "succeeded":
                    break
                verification.expire_all()
                time.sleep(0.01)
            else:
                raise AssertionError("restarted executor did not finish task")
    finally:
        executor.stop()


def test_persistent_executor_records_failure_and_deduplicates_active_job(
    db: Session,
) -> None:
    from app.db.session import SessionLocal
    from app.tasks.executor import PersistentTaskExecutor

    started = threading.Event()
    release = threading.Event()

    def dispatch(kind: str, resource_id: int, payload: dict[str, object]) -> None:
        del kind, resource_id, payload
        started.set()
        assert release.wait(timeout=2)
        raise ValueError("expected task failure")

    executor = PersistentTaskExecutor(SessionLocal, dispatch)
    executor.start()
    try:
        first = executor.enqueue(
            kind="test_failure",
            resource_id=7,
            payload={"path": "fixture"},
        )
        assert started.wait(timeout=2)
        duplicate = executor.enqueue(
            kind="test_failure",
            resource_id=7,
            payload={"path": "fixture"},
        )
        assert duplicate.id == first.id
        release.set()
        with SessionLocal() as verification:
            for _ in range(100):
                task = verification.get(AppTask, first.id)
                if task is not None and task.status == "failed":
                    break
                verification.expire_all()
                time.sleep(0.01)
            else:
                raise AssertionError("persistent task did not record failure")
            assert task is not None
            assert task.status == "failed"
            assert task.error_type == "ValueError"
            assert task.error_message == "expected task failure"
    finally:
        executor.stop()


def test_import_jobs_enqueue_durable_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import import_jobs

    enqueued: list[dict[str, object]] = []
    cancelled: list[dict[str, object]] = []
    monkeypatch.setattr(
        import_jobs.task_executor,
        "enqueue",
        lambda **kwargs: enqueued.append(kwargs),
    )
    monkeypatch.setattr(
        import_jobs.task_executor,
        "cancel_pending",
        lambda **kwargs: cancelled.append(kwargs),
    )

    import_jobs.enqueue_cptond_import(
        11, root=Path("fixture/cptond"), expected_checksum="cptond-sha"
    )
    import_jobs.enqueue_rail_import(
        12, pbf_path=Path("fixture/rail.osm.pbf"), expected_checksum="rail-sha"
    )
    import_jobs.cancel_cptond_import(11)

    assert enqueued == [
        {
            "kind": "cptond_import",
            "resource_id": 11,
            "payload": {
                "root": str(Path("fixture/cptond")),
                "expected_checksum": "cptond-sha",
            },
        },
        {
            "kind": "rail_import",
            "resource_id": 12,
            "payload": {
                "pbf_path": str(Path("fixture/rail.osm.pbf")),
                "expected_checksum": "rail-sha",
            },
        },
    ]
    assert cancelled == [{"kind": "cptond_import", "resource_id": 11}]


def test_cptond_import_job_restarts_partial_dataset(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    from app.db.session import SessionLocal
    from app.services import import_jobs

    network = seed_linear_network(db)
    dataset = db.get(DatasetVersion, network.dataset_id)
    assert dataset is not None
    dataset.status = "checking"
    dataset.processed_cities = 1
    db.commit()
    audit = SimpleNamespace(checksum="expected")
    monkeypatch.setattr("app.importers.cptond.audit_dataset", lambda root: audit)

    def complete_import(dataset_id: int, received_audit: object) -> None:
        assert received_audit is audit
        with SessionLocal() as worker_db:
            worker_dataset = worker_db.get(DatasetVersion, dataset_id)
            assert worker_dataset is not None
            assert worker_dataset.status == "staging"
            worker_dataset.status = "ready"
            worker_db.commit()

    monkeypatch.setattr("app.importers.cptond.run_dataset_import", complete_import)

    import_jobs._run_cptond_import(
        network.dataset_id,
        {"root": "fixture", "expected_checksum": "expected"},
    )

    db.expire_all()
    completed = db.get(DatasetVersion, network.dataset_id)
    assert completed is not None
    assert completed.status == "ready"
    assert db.get(City, network.city_id) is None


def test_cptond_import_job_persists_audit_failure(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    from app.services import import_jobs

    dataset = DatasetVersion(
        source_name="CPTOND",
        source_version="task-audit",
        captured_at="2025-06",
        license="CC BY 4.0",
        source_url="local",
        checksum="expected",
        importer_schema_version="test",
        status="staging",
    )
    db.add(dataset)
    db.commit()
    dataset_id = dataset.id

    def fail_audit(root: Path) -> None:
        del root
        raise OSError("dataset directory unavailable")

    monkeypatch.setattr("app.importers.cptond.audit_dataset", fail_audit)

    with pytest.raises(OSError, match="directory unavailable"):
        import_jobs._run_cptond_import(
            dataset_id,
            {"root": "missing", "expected_checksum": "expected"},
        )

    db.expire_all()
    failed = db.get(DatasetVersion, dataset_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "persistent_task_failed"
    assert failed.error_message == "dataset directory unavailable"


def test_rail_import_job_persists_domain_failure(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    from app.services import import_jobs

    dataset = RailDatasetVersion(
        source_name="test",
        source_url="local",
        source_timestamp="2026-08-31",
        pbf_checksum="r" * 64,
        extract_region="fixture",
        graph_version="task-fixture",
        profile_version="fixture",
        openrailrouting_version="fixture",
        graphhopper_version="fixture",
        license="ODbL-1.0",
        status="staging",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.commit()
    dataset_id = dataset.id

    def fail_import(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise ValueError("broken pbf")

    monkeypatch.setattr(import_jobs, "execute_rail_import", fail_import)

    with pytest.raises(ValueError, match="broken pbf"):
        import_jobs._run_rail_import(
            dataset_id,
            {
                "pbf_path": "fixture.osm.pbf",
                "expected_checksum": "r" * 64,
            },
        )

    db.expire_all()
    failed = db.get(RailDatasetVersion, dataset_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.quality_flags_json[0]["code"] == "rail_import_failed"
