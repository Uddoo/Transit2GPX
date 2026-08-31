from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError
from app.db.models import (
    JourneyLeg,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RailStation,
)
from app.db.session import get_db
from app.rail.importer import (
    RailImportError,
    load_graph_metadata,
    prepare_rail_dataset,
    rail_station_count,
)
from app.rail.sidecar import (
    EXPECTED_RAIL_PROFILES,
    RailSidecarError,
    fetch_sidecar_info,
)
from app.services.import_jobs import enqueue_rail_import

router = APIRouter(prefix="/rail/data", tags=["rail data"])

RailDataStatus = Literal[
    "disabled",
    "not_configured",
    "importing",
    "unavailable",
    "version_mismatch",
    "ready",
]


class RailDataStatusResponse(BaseModel):
    status: RailDataStatus
    enabled: bool
    sidecar_available: bool
    rail_dataset_version_id: int | None
    dataset_status: str | None
    station_count: int
    graph_version: str | None
    profile_version: str | None
    sidecar_graph_version: str | None
    sidecar_profile_version: str | None
    sidecar_pbf_checksum: str | None
    pbf_checksum: str | None
    source_url: str | None
    source_timestamp: str | None
    extract_region: str | None
    license: str | None
    profiles: list[str]
    bbox: tuple[float, float, float, float] | None
    error_code: str | None
    error_message: str | None


def _response(
    *,
    status: RailDataStatus,
    enabled: bool,
    sidecar_available: bool = False,
    dataset: RailDatasetVersion | None = None,
    station_count: int = 0,
    metadata: dict[str, Any] | None = None,
    profiles: list[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    sidecar_graph_version: str | None = None,
    sidecar_profile_version: str | None = None,
    sidecar_pbf_checksum: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> RailDataStatusResponse:
    metadata = metadata or {}
    return RailDataStatusResponse(
        status=status,
        enabled=enabled,
        sidecar_available=sidecar_available,
        rail_dataset_version_id=dataset.id if dataset else None,
        dataset_status=dataset.status if dataset else None,
        station_count=station_count,
        graph_version=metadata.get("graph_version"),
        profile_version=metadata.get("profile_version"),
        sidecar_graph_version=sidecar_graph_version,
        sidecar_profile_version=sidecar_profile_version,
        sidecar_pbf_checksum=sidecar_pbf_checksum,
        pbf_checksum=metadata.get("pbf_sha256"),
        source_url=metadata.get("source_url"),
        source_timestamp=metadata.get("source_timestamp"),
        extract_region=metadata.get("extract_region"),
        license=metadata.get("license"),
        profiles=profiles or [],
        bbox=bbox,
        error_code=error_code,
        error_message=error_message,
    )


class RailDataImportRequest(BaseModel):
    pbf_path: Path
    graph_version: str = Field(pattern=r"^[A-Za-z0-9._-]+$")


class RailDataImportResponse(BaseModel):
    import_id: int
    status: str
    graph_version: str
    pbf_checksum: str
    station_count: int
    error_code: str | None
    error_message: str | None


class RailStationDifferenceSample(BaseModel):
    osm_type: str
    osm_id: int
    from_name: str | None
    to_name: str | None
    changed_fields: list[str]


class RailDatasetDifferenceResponse(BaseModel):
    from_graph_version: str
    to_graph_version: str
    from_station_count: int
    to_station_count: int
    added_station_count: int
    removed_station_count: int
    changed_station_count: int
    unchanged_station_count: int
    affected_journey_count: int
    samples: list[RailStationDifferenceSample]


def _import_response(
    db: Session, dataset: RailDatasetVersion
) -> RailDataImportResponse:
    error = next(
        (
            flag
            for flag in reversed(dataset.quality_flags_json)
            if flag.get("code") == "rail_import_failed"
        ),
        None,
    )
    return RailDataImportResponse(
        import_id=dataset.id,
        status=dataset.status,
        graph_version=dataset.graph_version,
        pbf_checksum=dataset.pbf_checksum,
        station_count=rail_station_count(db, dataset.id),
        error_code=str(error["code"]) if error else None,
        error_message=str(error.get("message")) if error else None,
    )


@router.get("/status", response_model=RailDataStatusResponse)
def rail_data_status(db: Session = Depends(get_db)) -> RailDataStatusResponse:
    settings = get_settings()
    if not settings.rail_enabled:
        return _response(status="disabled", enabled=False)
    if not settings.rail_graph_version:
        return _response(
            status="not_configured",
            enabled=True,
            error_code="rail_graph_not_configured",
            error_message="尚未选择铁路图版本。",
        )
    try:
        metadata = load_graph_metadata(
            settings.resolved_rail_graph_root, settings.rail_graph_version
        )
    except RailImportError:
        return _response(
            status="not_configured",
            enabled=True,
            error_code="rail_graph_metadata_missing",
            error_message="铁路图版本不存在或元数据不完整。",
        )
    dataset = db.scalar(
        select(RailDatasetVersion).where(
            RailDatasetVersion.graph_version == metadata["graph_version"]
        )
    )
    count = rail_station_count(db, dataset.id) if dataset else 0
    if dataset is None:
        return _response(
            status="not_configured",
            enabled=True,
            metadata=metadata,
            error_code="rail_station_index_missing",
            error_message="铁路图已存在，但尚未从同一 PBF 导入车站索引。",
        )
    if dataset.status in {"staging", "building"}:
        return _response(
            status="importing",
            enabled=True,
            metadata=metadata,
            dataset=dataset,
            station_count=count,
            error_code="rail_station_index_building",
            error_message="正在从铁路 PBF 构建车站索引。",
        )
    if dataset.status != "ready" or dataset.pbf_checksum != metadata.get("pbf_sha256"):
        return _response(
            status="version_mismatch",
            enabled=True,
            metadata=metadata,
            dataset=dataset,
            station_count=count,
            error_code="rail_station_version_mismatch",
            error_message="铁路车站索引失败或与当前铁路图版本不一致。",
        )
    try:
        sidecar = fetch_sidecar_info(
            settings.rail_sidecar_url, settings.rail_sidecar_timeout_seconds
        )
    except RailSidecarError as error:
        return _response(
            status="unavailable",
            enabled=True,
            metadata=metadata,
            dataset=dataset,
            station_count=count,
            error_code=error.code,
            error_message=str(error),
        )
    missing_profiles = EXPECTED_RAIL_PROFILES - sidecar.profiles
    if missing_profiles:
        return _response(
            status="version_mismatch",
            enabled=True,
            sidecar_available=True,
            metadata=metadata,
            dataset=dataset,
            station_count=count,
            profiles=sorted(sidecar.profiles),
            bbox=sidecar.bbox,
            sidecar_graph_version=sidecar.graph_version,
            sidecar_profile_version=sidecar.profile_version,
            sidecar_pbf_checksum=sidecar.pbf_sha256,
            error_code="rail_profile_version_mismatch",
            error_message="铁路路径服务缺少当前版本要求的 Profile。",
        )
    expected_identity = (
        metadata["graph_version"],
        metadata["pbf_sha256"],
        metadata["profile_version"],
        metadata.get("openrailrouting_commit"),
    )
    actual_identity = (
        sidecar.graph_version,
        sidecar.pbf_sha256,
        sidecar.profile_version,
        sidecar.openrailrouting_commit,
    )
    if actual_identity != expected_identity:
        return _response(
            status="version_mismatch",
            enabled=True,
            sidecar_available=True,
            metadata=metadata,
            dataset=dataset,
            station_count=count,
            profiles=sorted(sidecar.profiles),
            bbox=sidecar.bbox,
            sidecar_graph_version=sidecar.graph_version,
            sidecar_profile_version=sidecar.profile_version,
            sidecar_pbf_checksum=sidecar.pbf_sha256,
            error_code="rail_sidecar_graph_version_mismatch",
            error_message="运行中的铁路路径服务与所选图、PBF 或 Profile 版本不一致。",
        )
    return _response(
        status="ready",
        enabled=True,
        sidecar_available=True,
        metadata=metadata,
        dataset=dataset,
        station_count=count,
        profiles=sorted(sidecar.profiles),
        bbox=sidecar.bbox,
        sidecar_graph_version=sidecar.graph_version,
        sidecar_profile_version=sidecar.profile_version,
        sidecar_pbf_checksum=sidecar.pbf_sha256,
    )


@router.get("/compare", response_model=RailDatasetDifferenceResponse)
def compare_rail_datasets(
    from_graph_version: str,
    to_graph_version: str,
    db: Session = Depends(get_db),
) -> RailDatasetDifferenceResponse:
    datasets = db.scalars(
        select(RailDatasetVersion).where(
            RailDatasetVersion.graph_version.in_([from_graph_version, to_graph_version])
        )
    ).all()
    by_graph_version = {dataset.graph_version: dataset for dataset in datasets}
    missing_versions = [
        graph_version
        for graph_version in (from_graph_version, to_graph_version)
        if graph_version not in by_graph_version
    ]
    if missing_versions:
        raise APIError(
            status_code=404,
            code="rail_dataset_not_found",
            message="没有找到要比较的铁路图版本。",
            details={"graph_versions": missing_versions},
        )
    from_dataset = by_graph_version[from_graph_version]
    to_dataset = by_graph_version[to_graph_version]
    from_stations = db.scalars(
        select(RailStation).where(
            RailStation.rail_dataset_version_id == from_dataset.id
        )
    ).all()
    to_stations = db.scalars(
        select(RailStation).where(RailStation.rail_dataset_version_id == to_dataset.id)
    ).all()
    from_by_osm = {
        (station.osm_type, station.osm_id): station for station in from_stations
    }
    to_by_osm = {(station.osm_type, station.osm_id): station for station in to_stations}
    from_keys = set(from_by_osm)
    to_keys = set(to_by_osm)
    added_keys = to_keys - from_keys
    removed_keys = from_keys - to_keys
    changed: list[tuple[tuple[str, int], list[str]]] = []
    for key in sorted(from_keys & to_keys):
        before = from_by_osm[key]
        after = to_by_osm[key]
        changed_fields = [
            field
            for field in (
                "name_cn",
                "name_en",
                "station_code",
                "city_name",
                "province_name",
                "lon",
                "lat",
                "match_status",
            )
            if getattr(before, field) != getattr(after, field)
        ]
        if changed_fields:
            changed.append((key, changed_fields))
    samples: list[RailStationDifferenceSample] = []
    for key in sorted(added_keys)[:10]:
        station = to_by_osm[key]
        samples.append(
            RailStationDifferenceSample(
                osm_type=key[0],
                osm_id=key[1],
                from_name=None,
                to_name=station.name_cn,
                changed_fields=["added"],
            )
        )
    for key in sorted(removed_keys)[:10]:
        station = from_by_osm[key]
        samples.append(
            RailStationDifferenceSample(
                osm_type=key[0],
                osm_id=key[1],
                from_name=station.name_cn,
                to_name=None,
                changed_fields=["removed"],
            )
        )
    remaining_sample_slots = max(0, 20 - len(samples))
    for key, changed_fields in changed[:remaining_sample_slots]:
        samples.append(
            RailStationDifferenceSample(
                osm_type=key[0],
                osm_id=key[1],
                from_name=from_by_osm[key].name_cn,
                to_name=to_by_osm[key].name_cn,
                changed_fields=changed_fields,
            )
        )
    affected_journey_count = int(
        db.scalar(
            select(func.count(func.distinct(JourneyLeg.journey_id)))
            .select_from(JourneyLeg)
            .join(
                RailJourneyEdgeSnapshot,
                RailJourneyEdgeSnapshot.journey_leg_id == JourneyLeg.id,
            )
            .where(RailJourneyEdgeSnapshot.rail_dataset_version_id == from_dataset.id)
        )
        or 0
    )
    return RailDatasetDifferenceResponse(
        from_graph_version=from_graph_version,
        to_graph_version=to_graph_version,
        from_station_count=len(from_stations),
        to_station_count=len(to_stations),
        added_station_count=len(added_keys),
        removed_station_count=len(removed_keys),
        changed_station_count=len(changed),
        unchanged_station_count=len(from_keys & to_keys) - len(changed),
        affected_journey_count=affected_journey_count,
        samples=samples,
    )


@router.post(
    "/imports",
    response_model=RailDataImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_rail_data_import(
    request: RailDataImportRequest,
    db: Session = Depends(get_db),
) -> RailDataImportResponse:
    settings = get_settings()
    pbf_path = request.pbf_path.expanduser().resolve()
    if not pbf_path.is_file() or not pbf_path.name.endswith(".osm.pbf"):
        raise APIError(
            status_code=422,
            code="rail_pbf_invalid",
            message="请选择本机存在的 .osm.pbf 文件。",
        )
    try:
        dataset = prepare_rail_dataset(
            db,
            graph_root=settings.resolved_rail_graph_root,
            graph_version=request.graph_version,
        )
    except RailImportError as error:
        raise APIError(
            status_code=422,
            code="rail_graph_metadata_invalid",
            message=str(error),
        ) from error
    if dataset.status in {"staging", "failed"}:
        enqueue_rail_import(
            dataset.id,
            pbf_path=pbf_path,
            expected_checksum=dataset.pbf_checksum,
        )
    return _import_response(db, dataset)


@router.get("/imports/{import_id}", response_model=RailDataImportResponse)
def get_rail_data_import(
    import_id: int,
    db: Session = Depends(get_db),
) -> RailDataImportResponse:
    dataset = db.get(RailDatasetVersion, import_id)
    if dataset is None:
        raise APIError(
            status_code=404,
            code="rail_import_not_found",
            message="铁路数据导入记录不存在。",
        )
    return _import_response(db, dataset)
