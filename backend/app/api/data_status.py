from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.base import AppMeta
from app.db.models import City, DatasetVersion, Line, RouteVariant
from app.db.session import get_db
from app.importers.capabilities import require_raw_import
from app.importers.city_pack import PackManifest
from app.services.import_jobs import cancel_cptond_import, enqueue_cptond_import

router = APIRouter(prefix="/data", tags=["data"])

DataStatus = Literal["not_configured", "importing", "ready", "failed", "cancelled"]
QualityStatus = Literal["not_available", "checking", "ready", "blocked"]
DatasetImportStatus = Literal["staging", "checking", "ready", "failed", "cancelled"]


class DataStatusResponse(BaseModel):
    status: DataStatus
    ready_available: bool
    import_id: int | None
    dataset: str | None
    captured_at: str | None
    license: str | None
    source_url: str | None
    checksum: str | None
    importer_schema_version: str | None
    cities: int
    route_count: int
    stop_count: int
    total_cities: int
    processed_cities: int
    ready_lines: int
    blocked_lines: int
    imported_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    quality_status: QualityStatus


class DatasetImportRequest(BaseModel):
    directory: str
    source_version: str | None = None


class DatasetImportResponse(BaseModel):
    import_id: int
    status: DatasetImportStatus
    route_count: int | None = None
    stop_count: int | None = None
    checksum: str | None = None
    total_cities: int = 0
    processed_cities: int = 0
    ready_lines: int = 0
    blocked_lines: int = 0
    error_code: str | None = None
    error_message: str | None = None


class QualityResponse(BaseModel):
    dataset_version_id: int | None
    ready_cities: int
    blocked_cities: int
    ready_lines: int
    blocked_lines: int
    ready_variants: int
    blocked_variants: int
    issues: list[dict[str, str | int]]


@router.get("/status", response_model=DataStatusResponse)
def data_status(db: Session = Depends(get_db)) -> DataStatusResponse:
    """Return the newest active or in-progress dataset status."""

    dataset = db.scalar(
        select(DatasetVersion)
        .where(
            DatasetVersion.status.in_(
                ["ready", "checking", "staging", "failed", "cancelled"]
            )
        )
        .order_by(DatasetVersion.imported_at.desc(), DatasetVersion.id.desc())
    )
    if dataset is not None:
        label = f"{dataset.source_name}-{dataset.source_version}"
        if dataset.importer_schema_version == "citypack-v1":
            label = f"城市数据包-{dataset.source_version}"
            if saved := db.get(AppMeta, f"citypack.manifest.{dataset.id}"):
                try:
                    manifest = PackManifest.model_validate_json(saved.value)
                    label = (
                        f"{manifest.city_name} · "
                        f"{manifest.source.name}-{manifest.source.version}"
                    )
                except ValueError:
                    pass
        status_by_dataset: dict[str, DataStatus] = {
            "ready": "ready",
            "checking": "importing",
            "staging": "importing",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        quality_by_dataset: dict[str, QualityStatus] = {
            "ready": "ready",
            "checking": "checking",
            "staging": "checking",
            "failed": "blocked",
            "cancelled": "blocked",
        }
        city_count = db.scalar(
            select(func.count())
            .select_from(City)
            .where(City.dataset_version_id == dataset.id)
        )
        ready_available = dataset.status == "ready" or bool(
            db.scalar(
                select(func.count())
                .select_from(DatasetVersion)
                .where(DatasetVersion.status == "ready")
            )
        )
        return DataStatusResponse(
            status=status_by_dataset[dataset.status],
            ready_available=ready_available,
            import_id=dataset.id,
            dataset=label,
            captured_at=dataset.captured_at,
            license=dataset.license,
            source_url=dataset.source_url,
            checksum=dataset.checksum,
            importer_schema_version=dataset.importer_schema_version,
            cities=city_count or 0,
            route_count=dataset.route_count,
            stop_count=dataset.stop_count,
            total_cities=dataset.total_cities,
            processed_cities=dataset.processed_cities,
            ready_lines=dataset.ready_lines,
            blocked_lines=dataset.blocked_lines,
            imported_at=dataset.imported_at,
            completed_at=dataset.completed_at,
            error_code=dataset.error_code,
            error_message=dataset.error_message,
            quality_status=quality_by_dataset[dataset.status],
        )

    return DataStatusResponse(
        status="not_configured",
        ready_available=False,
        import_id=None,
        dataset=None,
        captured_at=None,
        license=None,
        source_url=None,
        checksum=None,
        importer_schema_version=None,
        cities=0,
        route_count=0,
        stop_count=0,
        total_cities=0,
        processed_cities=0,
        ready_lines=0,
        blocked_lines=0,
        imported_at=None,
        completed_at=None,
        error_code=None,
        error_message=None,
        quality_status="not_available",
    )


@router.post(
    "/imports",
    response_model=DatasetImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_dataset_import(
    request: DatasetImportRequest,
) -> DatasetImportResponse:
    require_raw_import()
    from app.importers.cptond import (
        DatasetAuditError,
        audit_dataset,
        create_dataset_import,
    )

    try:
        audit = audit_dataset(Path(request.directory))
    except DatasetAuditError as error:
        raise APIError(
            status_code=422,
            code=error.code,
            message=str(error),
        ) from error
    handle = create_dataset_import(
        audit, request.source_version or audit.default_source_version
    )
    if handle.should_run:
        enqueue_cptond_import(
            handle.import_id,
            root=audit.root,
            expected_checksum=audit.checksum,
        )
    return DatasetImportResponse(
        import_id=handle.import_id,
        status=cast(DatasetImportStatus, handle.status),
        route_count=audit.route_count,
        stop_count=audit.stop_count,
        checksum=audit.checksum,
    )


@router.get("/imports/{import_id}", response_model=DatasetImportResponse)
def get_dataset_import(
    import_id: int, db: Session = Depends(get_db)
) -> DatasetImportResponse:
    dataset = db.get(DatasetVersion, import_id)
    if dataset is None:
        raise APIError(
            status_code=404,
            code="import_not_found",
            message="没有找到该数据导入任务",
            details={"import_id": import_id},
        )
    status_by_dataset: dict[str, DatasetImportStatus] = {
        "staging": "staging",
        "checking": "checking",
        "ready": "ready",
        "failed": "failed",
        "cancelled": "cancelled",
        "retired": "ready",
    }
    return DatasetImportResponse(
        import_id=dataset.id,
        status=status_by_dataset.get(dataset.status, "failed"),
        route_count=dataset.route_count,
        stop_count=dataset.stop_count,
        checksum=dataset.checksum,
        total_cities=dataset.total_cities,
        processed_cities=dataset.processed_cities,
        ready_lines=dataset.ready_lines,
        blocked_lines=dataset.blocked_lines,
        error_code=dataset.error_code,
        error_message=dataset.error_message,
    )


@router.post("/imports/{import_id}/cancel", response_model=DatasetImportResponse)
def cancel_dataset_import(
    import_id: int, db: Session = Depends(get_db)
) -> DatasetImportResponse:
    dataset = db.get(DatasetVersion, import_id)
    if dataset is None:
        raise APIError(
            status_code=404,
            code="import_not_found",
            message="没有找到该数据导入任务",
        )
    if dataset.status in {"ready", "failed", "cancelled"}:
        raise APIError(
            status_code=409,
            code="import_not_cancellable",
            message="该导入任务已经结束，无法取消。",
        )
    dataset.status = "cancelled"
    dataset.completed_at = datetime.now(UTC)
    dataset.error_code = "import_cancelled"
    dataset.error_message = "用户取消了数据导入"
    db.commit()
    cancel_cptond_import(dataset.id)
    return DatasetImportResponse(
        import_id=dataset.id,
        status="cancelled",
        route_count=dataset.route_count,
        stop_count=dataset.stop_count,
        checksum=dataset.checksum,
        total_cities=dataset.total_cities,
        processed_cities=dataset.processed_cities,
        ready_lines=dataset.ready_lines,
        blocked_lines=dataset.blocked_lines,
        error_code=dataset.error_code,
        error_message=dataset.error_message,
    )


@router.get("/quality", response_model=QualityResponse)
def quality_report(db: Session = Depends(get_db)) -> QualityResponse:
    dataset = db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.status.in_(["ready", "failed"]))
        .order_by(DatasetVersion.imported_at.desc(), DatasetVersion.id.desc())
    )
    if dataset is None:
        return QualityResponse(
            dataset_version_id=None,
            ready_cities=0,
            blocked_cities=0,
            ready_lines=0,
            blocked_lines=0,
            ready_variants=0,
            blocked_variants=0,
            issues=[],
        )
    city_ids = select(City.id).where(City.dataset_version_id == dataset.id)
    line_ids = select(Line.id).where(Line.city_id.in_(city_ids))
    blocked_city_rows = db.scalars(
        select(City).where(
            City.dataset_version_id == dataset.id, City.status == "blocked"
        )
    ).all()
    blocked_line_rows = db.scalars(
        select(Line).where(Line.city_id.in_(city_ids), Line.status == "blocked")
    ).all()
    blocked_variant_rows = db.scalars(
        select(RouteVariant).where(
            RouteVariant.line_id.in_(line_ids),
            RouteVariant.quality_status == "blocked",
        )
    ).all()
    issues: list[dict[str, str | int]] = []
    if dataset.error_code:
        issues.append(
            {
                "entity_type": "dataset",
                "entity_id": dataset.id,
                "name": f"{dataset.source_name}-{dataset.source_version}",
                "code": dataset.error_code,
                "message": dataset.error_message or "数据导入失败",
            }
        )
    issues.extend(
        {
            "entity_type": "city",
            "entity_id": city.id,
            "name": city.name_cn,
            "code": "no_ready_lines",
            "message": "该城市没有线路通过质量门禁。",
        }
        for city in blocked_city_rows
    )
    issues.extend(
        {
            "entity_type": "line",
            "entity_id": line.id,
            "name": line.name_cn,
            "code": "no_ready_variants",
            "message": "该线路没有方向变体通过质量门禁。",
        }
        for line in blocked_line_rows
    )
    for variant in blocked_variant_rows:
        flags = variant.quality_flags_json or [
            {"code": "quality_blocked", "message": "线路方向未通过质量门禁。"}
        ]
        for flag in flags:
            issues.append(
                {
                    "entity_type": "variant",
                    "entity_id": variant.id,
                    "name": variant.source_route_name or variant.source_route_id,
                    "code": str(flag.get("code", "quality_blocked")),
                    "message": str(flag.get("message", "线路方向未通过质量门禁。")),
                }
            )
    return QualityResponse(
        dataset_version_id=dataset.id,
        ready_cities=int(
            db.scalar(
                select(func.count())
                .select_from(City)
                .where(City.dataset_version_id == dataset.id, City.status == "ready")
            )
            or 0
        ),
        blocked_cities=int(
            db.scalar(
                select(func.count())
                .select_from(City)
                .where(City.dataset_version_id == dataset.id, City.status == "blocked")
            )
            or 0
        ),
        ready_lines=int(
            db.scalar(
                select(func.count())
                .select_from(Line)
                .where(Line.city_id.in_(city_ids), Line.status == "ready")
            )
            or 0
        ),
        blocked_lines=int(
            db.scalar(
                select(func.count())
                .select_from(Line)
                .where(Line.city_id.in_(city_ids), Line.status == "blocked")
            )
            or 0
        ),
        ready_variants=int(
            db.scalar(
                select(func.count())
                .select_from(RouteVariant)
                .where(
                    RouteVariant.line_id.in_(line_ids),
                    RouteVariant.quality_status == "ready",
                )
            )
            or 0
        ),
        blocked_variants=int(
            db.scalar(
                select(func.count())
                .select_from(RouteVariant)
                .where(
                    RouteVariant.line_id.in_(line_ids),
                    RouteVariant.quality_status == "blocked",
                )
            )
            or 0
        ),
        issues=issues,
    )
