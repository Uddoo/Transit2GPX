from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.models import DatasetVersion, RailDatasetVersion
from app.db.session import SessionLocal
from app.rail.importer import execute_rail_import
from app.tasks import task_executor

CPTOND_IMPORT_TASK = "cptond_import"
RAIL_IMPORT_TASK = "rail_import"
TaskHandler = Callable[[int, dict[str, Any]], None]


def enqueue_cptond_import(
    dataset_id: int, *, root: Path, expected_checksum: str
) -> None:
    task_executor.enqueue(
        kind=CPTOND_IMPORT_TASK,
        resource_id=dataset_id,
        payload={"root": str(root), "expected_checksum": expected_checksum},
    )


def enqueue_rail_import(
    dataset_id: int, *, pbf_path: Path, expected_checksum: str
) -> None:
    task_executor.enqueue(
        kind=RAIL_IMPORT_TASK,
        resource_id=dataset_id,
        payload={
            "pbf_path": str(pbf_path),
            "expected_checksum": expected_checksum,
        },
    )


def cancel_cptond_import(dataset_id: int) -> None:
    task_executor.cancel_pending(kind=CPTOND_IMPORT_TASK, resource_id=dataset_id)


def _run_cptond_import(dataset_id: int, payload: dict[str, Any]) -> None:
    from app.importers.capabilities import require_raw_import
    from app.importers.cleanup import clear_dataset_cities

    try:
        require_raw_import()
        from app.importers.cptond import audit_dataset, run_dataset_import

        audit = audit_dataset(Path(str(payload["root"])))
        if audit.checksum != payload.get("expected_checksum"):
            raise RuntimeError("CPTOND 数据目录在任务入队后发生了变化。")
        with SessionLocal() as db:
            dataset = db.get(DatasetVersion, dataset_id)
            if dataset is None:
                raise RuntimeError("CPTOND 导入记录不存在。")
            if dataset.status == "checking":
                clear_dataset_cities(db, dataset_id)
                dataset.status = "staging"
                dataset.processed_cities = 0
                dataset.ready_lines = 0
                dataset.blocked_lines = 0
                db.commit()
        run_dataset_import(dataset_id, audit)
        with SessionLocal() as db:
            dataset = db.get(DatasetVersion, dataset_id)
            if dataset is None:
                raise RuntimeError("CPTOND 导入记录不存在。")
            if dataset.status == "cancelled":
                raise CancelledError("CPTOND 导入已取消。")
            if dataset.status != "ready":
                raise RuntimeError(dataset.error_message or "CPTOND 导入失败。")
    except CancelledError:
        raise
    except Exception as error:
        with SessionLocal() as db:
            dataset = db.get(DatasetVersion, dataset_id)
            if dataset is not None and dataset.status not in {"ready", "cancelled"}:
                clear_dataset_cities(db, dataset_id)
                dataset.status = "failed"
                dataset.completed_at = datetime.now(UTC)
                dataset.error_code = dataset.error_code or getattr(
                    error, "code", "persistent_task_failed"
                )
                dataset.error_message = dataset.error_message or str(error)[:2000]
                db.commit()
        raise


def _run_rail_import(dataset_id: int, payload: dict[str, Any]) -> None:
    pbf_path = Path(str(payload["pbf_path"]))
    with SessionLocal() as db:
        try:
            dataset = db.get(RailDatasetVersion, dataset_id)
            if dataset is None:
                raise RuntimeError("铁路数据导入记录不存在。")
            if dataset.pbf_checksum != payload.get("expected_checksum"):
                raise RuntimeError("铁路 PBF 身份与入队任务不一致。")
            execute_rail_import(db, dataset_id=dataset_id, pbf_path=pbf_path)
        except Exception as error:
            db.rollback()
            dataset = db.get(RailDatasetVersion, dataset_id)
            if dataset is not None:
                dataset.status = "failed"
                dataset.quality_flags_json = [
                    {
                        "code": "rail_import_failed",
                        "message": str(error),
                        "error_type": type(error).__name__,
                    }
                ]
                db.commit()
            raise


TASK_HANDLERS: dict[str, TaskHandler] = {
    CPTOND_IMPORT_TASK: _run_cptond_import,
    RAIL_IMPORT_TASK: _run_rail_import,
}
