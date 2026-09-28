"""Recover abandoned jobs on startup of the single local API process."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import DatasetVersion, ImportBatch, RailDatasetVersion


def recover_interrupted_imports(db: Session) -> None:
    message = "服务在导入完成前停止，请重新导入以安全重试。"
    db.execute(
        update(DatasetVersion)
        .where(DatasetVersion.status.in_(["staging", "checking"]))
        .values(
            status="failed",
            completed_at=datetime.now(UTC),
            error_code="import_interrupted",
            error_message=message,
        )
    )
    for dataset in db.scalars(
        select(RailDatasetVersion).where(
            RailDatasetVersion.status.in_(["staging", "building"])
        )
    ):
        dataset.status = "failed"
        dataset.completed_at = datetime.now(UTC)
        dataset.quality_flags_json = [
            {"code": "rail_import_interrupted", "message": message}
        ]
    db.execute(
        update(ImportBatch)
        .where(ImportBatch.status.in_(["parsing", "committing"]))
        .values(
            status="failed",
            run_token=None,
            error_message="服务已重启，可继续处理此批次的剩余行。",
        )
    )
    db.commit()
