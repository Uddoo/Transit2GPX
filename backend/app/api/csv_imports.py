from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal, TypeVar, cast
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.journeys import RailJourneyLegCreate, _save_rail_leg
from app.core.errors import APIError
from app.db.active_cities import current_city_ids
from app.db.models import (
    City,
    ImportBatch,
    ImportRow,
    Journey,
    JourneyLeg,
    JourneyLegEdge,
    Line,
    RailStation,
    Station,
)
from app.db.session import SessionLocal, get_db
from app.matching.names import (
    normalize_city_name,
    normalize_line_name,
)
from app.matching.rail_stations import search_ready_rail_stations
from app.matching.stations import exact_line_station_matches
from app.providers import CSV_TIMETABLE_PROVIDER, METRO_PROVIDER, RAILWAY_PROVIDER
from app.rail.resolver import (
    RailPathCandidate,
    RailResolutionError,
    RailTrainType,
)
from app.routing.resolver import ResolvedCandidate

router = APIRouter(prefix="/import-batches", tags=["csv-import"])

KNOWN_COLUMNS = {
    "journey_id",
    "leg_no",
    "mode",
    "travel_date",
    "train_no",
    "train_type",
    "city",
    "line",
    "from_station",
    "to_station",
    "via_stations",
    "route_hint",
    "start_station",
    "end_station",
    "traveled_at",
    "direction",
    "via_station",
    "note",
}
_TRAIN_TYPES = {"G", "C", "D", "S", "Z", "T", "K", "Y", "OTHER"}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
T = TypeVar("T")


class ImportBatchResponse(BaseModel):
    id: int
    filename: str
    encoding: str
    total_rows: int
    processed_rows: int
    error_message: str | None
    resolved_rows: int
    review_rows: int
    failed_rows: int
    status: str
    created_at: datetime
    committed_at: datetime | None


class ImportRowResponse(BaseModel):
    id: int
    row_no: int
    raw: dict[str, Any]
    normalized: dict[str, Any]
    resolution_status: str
    matched_city_id: int | None
    matched_line_id: int | None
    matched_start_station_id: int | None
    matched_end_station_id: int | None
    matched_rail_start_station_id: int | None
    matched_rail_end_station_id: int | None
    selected_candidate_id: str | None
    candidates: list[dict[str, Any]]
    error_code: str | None
    error_message: str | None


class ImportRowsResponse(BaseModel):
    items: list[ImportRowResponse]
    total: int


class ImportRowPatch(BaseModel):
    city: str | None = Field(default=None, max_length=120)
    line: str | None = Field(default=None, max_length=160)
    start_station: str | None = Field(default=None, max_length=200)
    end_station: str | None = Field(default=None, max_length=200)
    direction: str | None = Field(default=None, max_length=120)
    via_station: str | None = Field(default=None, max_length=500)
    traveled_at: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=2000)
    mode: Literal["metro", "rail"] | None = None
    travel_date: str | None = Field(default=None, max_length=20)
    train_no: str | None = Field(default=None, max_length=80)
    train_type: str | None = Field(default=None, max_length=20)
    from_station: str | None = Field(default=None, max_length=240)
    to_station: str | None = Field(default=None, max_length=240)
    via_stations: str | None = Field(default=None, max_length=2000)
    route_hint: str | None = Field(default=None, max_length=500)
    selected_candidate_id: str | None = Field(default=None, max_length=160)
    ignored: bool | None = None


class CommitRequest(BaseModel):
    strategy: Literal["all", "resolved_only"] = "all"


def _batch_response(batch: ImportBatch) -> ImportBatchResponse:
    return ImportBatchResponse(
        id=batch.id,
        filename=batch.filename,
        encoding=batch.encoding,
        total_rows=batch.total_rows,
        processed_rows=batch.processed_rows,
        error_message=batch.error_message,
        resolved_rows=batch.resolved_rows,
        review_rows=batch.review_rows,
        failed_rows=batch.failed_rows,
        status=batch.status,
        created_at=batch.created_at,
        committed_at=batch.committed_at,
    )


def _row_response(row: ImportRow) -> ImportRowResponse:
    return ImportRowResponse(
        id=row.id,
        row_no=row.row_no,
        raw=row.raw_json,
        normalized=row.normalized_json,
        resolution_status=row.resolution_status,
        matched_city_id=row.matched_city_id,
        matched_line_id=row.matched_line_id,
        matched_start_station_id=row.matched_start_station_id,
        matched_end_station_id=row.matched_end_station_id,
        matched_rail_start_station_id=row.matched_rail_start_station_id,
        matched_rail_end_station_id=row.matched_rail_end_station_id,
        selected_candidate_id=row.selected_candidate_id,
        candidates=row.candidate_json,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _candidate_json(candidate: ResolvedCandidate) -> dict[str, Any]:
    return {
        "mode": "metro",
        "candidate_id": candidate.candidate_id,
        "digest": candidate.digest,
        "dataset_version_id": candidate.dataset_version_id,
        "route_variant_id": candidate.route_variant_id,
        "line_name": candidate.line_name,
        "direction_name": candidate.direction_name,
        "distance_m": candidate.distance_m,
        "station_ids": list(candidate.station_ids),
        "edge_ids": list(candidate.edge_ids),
        "reversed_edges": list(candidate.reversed_edges),
        "warnings": list(candidate.warnings),
    }


def _rail_candidate_json(candidate: RailPathCandidate) -> dict[str, Any]:
    return {
        "mode": "rail",
        "candidate_id": candidate.candidate_id,
        "digest": candidate.digest,
        "rail_dataset_version_id": candidate.rail_dataset_version_id,
        "graph_version": candidate.graph_version,
        "profile_version": candidate.profile_version,
        "scoring_version": candidate.scoring_version,
        "routing_profile": candidate.routing_profile,
        "direction_name": candidate.routing_profile,
        "distance_m": candidate.distance_m,
        "duration_ms": candidate.duration_ms,
        "station_ids": list(candidate.station_ids),
        "geometry": {
            "type": "LineString",
            "coordinates": [list(point) for point in candidate.coordinates],
        },
        "way_ranges": [
            {
                "start_index": item.start_index,
                "end_index": item.end_index,
                "osm_way_id": item.osm_way_id,
            }
            for item in candidate.way_ranges
        ],
        "score": candidate.score,
        "score_details": list(candidate.score_details),
        "warnings": list(candidate.warnings),
        "can_commit": candidate.can_commit,
    }


def _single_match(items: Sequence[T]) -> T | None:
    return items[0] if len(items) == 1 else None


def _normalized_csv_values(cleaned: dict[str, str]) -> dict[str, str]:
    mode = (cleaned.get("mode") or "metro").lower()
    travel_date = cleaned.get("travel_date") or cleaned.get("traveled_at", "")
    from_station = cleaned.get("from_station") or cleaned.get("start_station", "")
    to_station = cleaned.get("to_station") or cleaned.get("end_station", "")
    via_stations = cleaned.get("via_stations") or cleaned.get("via_station", "")
    normalized = {key: cleaned.get(key, "") for key in KNOWN_COLUMNS}
    normalized.update(
        {
            "mode": mode,
            "travel_date": travel_date,
            "traveled_at": travel_date,
            "from_station": from_station,
            "start_station": from_station,
            "to_station": to_station,
            "end_station": to_station,
            "via_stations": via_stations,
            "via_station": via_stations,
        }
    )
    return normalized


def _exact_rail_station(db: Session, value: str) -> RailStation | None:
    matches = search_ready_rail_stations(db, value=value, limit=100)
    exact = [match.station for match in matches if match.score == 100]
    return _single_match(exact)


def _rail_train_type(values: dict[str, Any]) -> RailTrainType | None:
    raw_type = str(values.get("train_type", "")).strip().upper()
    train_no = str(values.get("train_no", "")).strip().upper()
    inferred = train_no[:1] if train_no[:1] in _TRAIN_TYPES else "OTHER"
    train_type = raw_type or inferred
    if train_type not in _TRAIN_TYPES:
        return None
    return cast(RailTrainType, train_type)


def _resolve_rail_row(db: Session, row: ImportRow, travel_date: str) -> None:
    values = row.normalized_json
    if not travel_date:
        row.resolution_status = "unresolved"
        row.error_code = "rail_date_required"
        row.error_message = "铁路行程必须填写 travel_date。"
        return
    train_type = _rail_train_type(values)
    if train_type is None:
        row.resolution_status = "unresolved"
        row.error_code = "rail_train_type_invalid"
        row.error_message = "train_type 必须是 G/C/D/S/Z/T/K/Y/OTHER。"
        return
    values = {**values, "train_type": train_type}
    row.normalized_json = values
    start_name = str(values.get("from_station", ""))
    end_name = str(values.get("to_station", ""))
    start = _exact_rail_station(db, start_name)
    end = _exact_rail_station(db, end_name)
    if start is None or end is None or start.id == end.id:
        row.resolution_status = "unresolved"
        row.error_code = "rail_station_not_unique"
        row.error_message = "铁路起终点未找到、存在同名候选或两者相同。"
        return
    row.matched_rail_start_station_id = start.id
    row.matched_rail_end_station_id = end.id
    via_ids: list[int] = []
    for via_name in str(values.get("via_stations", "")).split("|"):
        if not via_name.strip():
            continue
        via = _exact_rail_station(db, via_name)
        if via is None:
            row.resolution_status = "unresolved"
            row.error_code = "rail_via_station_not_unique"
            row.error_message = f"铁路途经站“{via_name}”未找到或不唯一。"
            return
        via_ids.append(via.id)
    try:
        facts = CSV_TIMETABLE_PROVIDER.create_facts(
            travel_date=date.fromisoformat(travel_date),
            train_no=str(values.get("train_no", "")).strip() or None,
            train_type=train_type,
            start_station_id=start.id,
            end_station_id=end.id,
            via_station_ids=via_ids,
            route_hint=str(values.get("route_hint", "")).strip() or None,
        )
        resolution = RAILWAY_PROVIDER.resolve(db, facts)
    except RailResolutionError as error:
        row.resolution_status = "unresolved"
        row.error_code = error.code
        row.error_message = str(error)
        return
    row.candidate_json = [
        _rail_candidate_json(candidate) for candidate in resolution.candidates
    ]
    row.resolution_status = resolution.status
    if resolution.status == "resolved":
        row.selected_candidate_id = resolution.candidates[0].candidate_id
    elif resolution.status == "needs_review":
        row.error_code = "rail_path_needs_review"
        row.error_message = "找到多个铁路候选或带质量警告，请人工确认。"
    else:
        row.error_code = "rail_path_unresolved"
        row.error_message = "没有找到依次通过全部有序车站的铁路路径。"


def _resolve_row(db: Session, row: ImportRow) -> None:
    values = row.normalized_json
    row.matched_city_id = None
    row.matched_line_id = None
    row.matched_start_station_id = None
    row.matched_end_station_id = None
    row.matched_rail_start_station_id = None
    row.matched_rail_end_station_id = None
    row.selected_candidate_id = None
    row.candidate_json = []
    row.error_code = None
    row.error_message = None

    mode = str(values.get("mode", "metro")).strip().lower() or "metro"
    if mode not in {"metro", "rail"}:
        row.resolution_status = "unresolved"
        row.error_code = "transport_mode_invalid"
        row.error_message = "mode 必须是 metro 或 rail。"
        return
    traveled_at = str(values.get("travel_date", "")).strip()
    if traveled_at:
        try:
            date.fromisoformat(traveled_at)
        except ValueError:
            row.resolution_status = "unresolved"
            row.error_code = "invalid_date"
            row.error_message = "日期必须使用 YYYY-MM-DD。"
            return
    leg_no = str(values.get("leg_no", "")).strip()
    if leg_no:
        try:
            parsed_leg_no = int(leg_no)
        except ValueError:
            parsed_leg_no = 0
        if parsed_leg_no < 1:
            row.resolution_status = "unresolved"
            row.error_code = "invalid_leg_no"
            row.error_message = "leg_no 必须是正整数。"
            return

    if mode == "rail":
        _resolve_rail_row(db, row, traveled_at)
        return

    if not all(str(values.get(field, "")).strip() for field in ("city", "line")):
        row.resolution_status = "unresolved"
        row.error_code = "metro_fields_missing"
        row.error_message = "地铁行必须填写 city 与 line。"
        return

    city_key = normalize_city_name(str(values.get("city", "")))
    cities = [
        city
        for city in db.scalars(
            select(City).where(City.id.in_(current_city_ids()))
        ).all()
        if city_key
        in {
            normalize_city_name(city.name_cn),
            normalize_city_name(city.name_en or ""),
        }
    ]
    city = _single_match(cities)
    if city is None:
        row.resolution_status = "unresolved"
        row.error_code = "city_not_unique"
        row.error_message = "城市未找到或存在同名候选。"
        return
    row.matched_city_id = city.id

    line_key = normalize_line_name(str(values.get("line", "")))
    lines = [
        line
        for line in db.scalars(
            select(Line).where(Line.city_id == city.id, Line.status == "ready")
        ).all()
        if line_key
        in {
            line.normalized_name,
            normalize_line_name(line.name_cn),
            normalize_line_name(line.name_en or ""),
        }
    ]
    line = _single_match(lines)
    if line is None:
        row.resolution_status = "unresolved"
        row.error_code = "line_not_unique"
        row.error_message = "线路未找到或存在多个候选。"
        return
    row.matched_line_id = line.id

    def station_match(field: str) -> Station | None:
        return _single_match(
            exact_line_station_matches(
                db,
                line_id=line.id,
                value=str(values.get(field, "")),
            )
        )

    start = station_match("start_station")
    end = station_match("end_station")
    if start is None or end is None or start.id == end.id:
        row.resolution_status = "unresolved"
        row.error_code = "station_not_unique"
        row.error_message = "起终点未找到、存在同名候选或两者相同。"
        return
    row.matched_start_station_id = start.id
    row.matched_end_station_id = end.id

    via_ids: list[int] = []
    for via_name in str(values.get("via_station", "")).split("|"):
        if not via_name.strip():
            continue
        via = _single_match(
            exact_line_station_matches(db, line_id=line.id, value=via_name)
        )
        if via is None:
            row.resolution_status = "unresolved"
            row.error_code = "via_station_not_unique"
            row.error_message = f"途经站“{via_name}”未找到或不唯一。"
            return
        via_ids.append(via.id)

    resolution = METRO_PROVIDER.resolve_line(
        db,
        line_id=line.id,
        start_station_id=start.id,
        end_station_id=end.id,
        direction=str(values.get("direction", "")) or "auto",
        via_station_ids=via_ids,
    )
    row.candidate_json = [
        _candidate_json(candidate) for candidate in resolution.candidates
    ]
    row.resolution_status = resolution.status
    if resolution.status == "resolved":
        row.selected_candidate_id = resolution.candidates[0].candidate_id
    elif resolution.status == "needs_review":
        row.error_code = "path_needs_review"
        row.error_message = "找到多个方向或带质量警告的候选，请人工确认。"
    else:
        row.error_code = "path_unresolved"
        row.error_message = "没有找到包含起终点的可用线路区间。"


def _refresh_counts(db: Session, batch: ImportBatch) -> None:
    db.flush()
    counts = {
        status: count
        for status, count in db.execute(
            select(ImportRow.resolution_status, func.count())
            .where(ImportRow.batch_id == batch.id)
            .group_by(ImportRow.resolution_status)
        ).all()
    }
    batch.total_rows = sum(counts.values())
    batch.resolved_rows = counts.get("resolved", 0) + counts.get("committed", 0)
    batch.review_rows = counts.get("needs_review", 0)
    pending = int(
        db.scalar(
            select(func.count())
            .select_from(ImportRow)
            .where(
                ImportRow.batch_id == batch.id, ImportRow.error_code == "csv_pending"
            )
        )
        or 0
    )
    batch.failed_rows = counts.get("unresolved", 0) - pending
    batch.processed_rows = batch.total_rows - pending
    if batch.status not in {"committed", "cancelled", "parsing", "failed"}:
        batch.status = "ready_for_review"


def _require_batch(db: Session, batch_id: int) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None:
        raise APIError(
            status_code=404,
            code="import_batch_not_found",
            message="没有找到这个 CSV 导入批次。",
        )
    return batch


def _require_reviewable(batch: ImportBatch) -> None:
    if batch.status != "ready_for_review":
        raise APIError(
            status_code=409,
            code="batch_not_ready",
            message="请等待解析完成；已暂停或中断的批次可先继续解析。",
        )


def run_import_batch(batch_id: int, run_token: str) -> None:
    """Resolve off the event loop, committing one row at a time for recovery.

    A generation token prevents an old worker from writing after cancel/resume.
    Each transaction owns its session; no request session crosses threads.
    """
    try:
        while True:
            with SessionLocal() as db:
                batch = db.get(ImportBatch, batch_id)
                if (
                    batch is None
                    or batch.status != "parsing"
                    or batch.run_token != run_token
                ):
                    return
                row = db.scalar(
                    select(ImportRow)
                    .where(
                        ImportRow.batch_id == batch_id,
                        ImportRow.error_code == "csv_pending",
                    )
                    .order_by(ImportRow.row_no)
                    .limit(1)
                )
                if row is None:
                    db.execute(
                        update(ImportBatch)
                        .where(
                            ImportBatch.id == batch_id,
                            ImportBatch.status == "parsing",
                            ImportBatch.run_token == run_token,
                        )
                        .values(
                            status="ready_for_review",
                            run_token=None,
                            error_message=None,
                        )
                    )
                    db.commit()
                    return
                _resolve_row(db, row)
                claimed = db.execute(
                    update(ImportBatch)
                    .where(
                        ImportBatch.id == batch_id,
                        ImportBatch.status == "parsing",
                        ImportBatch.run_token == run_token,
                    )
                    .values(
                        processed_rows=ImportBatch.processed_rows + 1,
                        resolved_rows=ImportBatch.resolved_rows
                        + int(row.resolution_status == "resolved"),
                        review_rows=ImportBatch.review_rows
                        + int(row.resolution_status == "needs_review"),
                        failed_rows=ImportBatch.failed_rows
                        + int(row.resolution_status == "unresolved"),
                    )
                    .returning(ImportBatch.id)
                ).scalar_one_or_none()
                if claimed is None:
                    db.rollback()
                    return
                db.commit()
    except Exception:
        with SessionLocal() as db:
            db.execute(
                update(ImportBatch)
                .where(
                    ImportBatch.id == batch_id,
                    ImportBatch.status == "parsing",
                    ImportBatch.run_token == run_token,
                )
                .values(
                    status="failed",
                    run_token=None,
                    error_message="解析已中断，可继续处理剩余行；已完成的审核结果仍保留。",
                )
            )
            db.commit()


@router.post("/{batch_id}/cancel", response_model=ImportBatchResponse)
def cancel_import_batch(
    batch_id: int, db: Session = Depends(get_db)
) -> ImportBatchResponse:
    changed = db.execute(
        update(ImportBatch)
        .where(
            ImportBatch.id == batch_id,
            ImportBatch.status == "parsing",
        )
        .values(status="cancelled", run_token=None)
        .returning(ImportBatch.id)
    ).scalar_one_or_none()
    if changed is None:
        _require_batch(db, batch_id)
        raise APIError(
            status_code=409,
            code="batch_not_cancellable",
            message="仅正在解析的批次可以暂停。",
        )
    db.commit()
    return _batch_response(_require_batch(db, batch_id))


@router.post("/{batch_id}/resume", response_model=ImportBatchResponse, status_code=202)
def resume_import_batch(
    batch_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> ImportBatchResponse:
    token = uuid4().hex
    changed = db.execute(
        update(ImportBatch)
        .where(
            ImportBatch.id == batch_id,
            ImportBatch.status.in_(["cancelled", "failed"]),
        )
        .values(status="parsing", run_token=token, error_message=None)
        .returning(ImportBatch.id)
    ).scalar_one_or_none()
    if changed is None:
        _require_batch(db, batch_id)
        raise APIError(
            status_code=409,
            code="batch_not_resumable",
            message="仅已暂停或中断的批次可以继续。",
        )
    db.commit()
    background_tasks.add_task(run_import_batch, batch_id, token)
    return _batch_response(_require_batch(db, batch_id))


@router.get("/template.csv")
def csv_template() -> Response:
    content = (
        "journey_id,leg_no,mode,travel_date,train_no,train_type,city,line,"
        "from_station,to_station,via_stations,route_hint,direction,note\r\n"
        "20260820-01,1,rail,2026-08-20,G1,G,,,上海虹桥,杭州东,"
        "嘉兴南|桐乡,沪昆高速铁路,,铁路示例\r\n"
        "20260822-01,1,metro,2026-08-22,,,上海,1号线,人民广场,"
        "徐家汇,,,,地铁示例\r\n"
    )
    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="transit2gpx_template.csv"'
        },
    )


@router.post("", response_model=ImportBatchResponse, status_code=201)
def create_import_batch(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(),
    db: Session = Depends(get_db),
) -> ImportBatchResponse:
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise APIError(
            status_code=413,
            code="csv_too_large",
            message="CSV 文件不能超过 5 MB。",
        )
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise APIError(
            status_code=422,
            code="csv_encoding_invalid",
            message="CSV 只接受 UTF-8 或 UTF-8-SIG 编码。",
        ) from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = {column.strip() for column in (reader.fieldnames or []) if column}
    missing: list[str] = []
    if not ({"from_station", "start_station"} & columns):
        missing.append("from_station")
    if not ({"to_station", "end_station"} & columns):
        missing.append("to_station")
    if missing:
        raise APIError(
            status_code=422,
            code="csv_columns_missing",
            message="CSV 缺少必填列。",
            details={"columns": missing},
        )
    batch = ImportBatch(
        filename=(file.filename or "import.csv")[:260],
        encoding="utf-8-sig" if content.startswith(b"\xef\xbb\xbf") else "utf-8",
        status="parsing",
        run_token=uuid4().hex,
    )
    db.add(batch)
    db.flush()
    try:
        for row_no, raw in enumerate(reader, start=2):
            if row_no - 1 > MAX_ROWS:
                raise APIError(
                    status_code=413,
                    code="csv_too_many_rows",
                    message="CSV 最多允许 10,000 行。",
                )
            if None in raw or any(
                value is not None and not isinstance(value, str)
                for value in raw.values()
            ):
                raise APIError(
                    status_code=422,
                    code="csv_row_malformed",
                    message=f"CSV 第 {row_no} 行的字段数量与表头不一致。",
                    details={"row_no": row_no},
                )
            cleaned = {key.strip(): (value or "").strip() for key, value in raw.items()}
            normalized = _normalized_csv_values(cleaned)
            row = ImportRow(
                batch_id=batch.id,
                row_no=row_no,
                raw_json=cleaned,
                normalized_json=normalized,
                resolution_status="unresolved",
                error_code="csv_pending",
            )
            db.add(row)
        db.flush()
        if not db.scalar(
            select(ImportRow.id).where(ImportRow.batch_id == batch.id).limit(1)
        ):
            raise APIError(
                status_code=422,
                code="csv_empty",
                message="CSV 没有数据行。",
            )
        _refresh_counts(db, batch)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(batch)
    assert batch.run_token is not None
    background_tasks.add_task(run_import_batch, batch.id, batch.run_token)
    return _batch_response(batch)


@router.get("/{batch_id}", response_model=ImportBatchResponse)
def get_import_batch(
    batch_id: int, db: Session = Depends(get_db)
) -> ImportBatchResponse:
    return _batch_response(_require_batch(db, batch_id))


@router.get("/{batch_id}/rows", response_model=ImportRowsResponse)
def list_import_rows(
    batch_id: int,
    status: Literal["resolved", "needs_review", "unresolved", "ignored", "committed"]
    | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ImportRowsResponse:
    batch = _require_batch(db, batch_id)
    del batch
    statement = select(ImportRow).where(ImportRow.batch_id == batch_id)
    if status:
        statement = statement.where(ImportRow.resolution_status == status)
    rows = db.scalars(
        statement.order_by(ImportRow.row_no).offset(offset).limit(limit)
    ).all()
    total = int(
        db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    return ImportRowsResponse(items=[_row_response(row) for row in rows], total=total)


@router.patch("/{batch_id}/rows/{row_id}", response_model=ImportRowResponse)
def patch_import_row(
    batch_id: int,
    row_id: int,
    request: ImportRowPatch,
    db: Session = Depends(get_db),
) -> ImportRowResponse:
    batch = _require_batch(db, batch_id)
    if batch.status == "committed":
        raise APIError(
            status_code=409,
            code="batch_already_committed",
            message="已提交批次不能再修改审核行。",
        )
    _require_reviewable(batch)
    row = db.get(ImportRow, row_id)
    if row is None or row.batch_id != batch_id:
        raise APIError(
            status_code=404, code="import_row_not_found", message="没有找到这一行。"
        )
    if request.ignored is True:
        row.resolution_status = "ignored"
        row.error_code = None
        row.error_message = None
    else:
        values = dict(row.normalized_json)
        for field in (
            "mode",
            "travel_date",
            "train_no",
            "train_type",
            "city",
            "line",
            "from_station",
            "to_station",
            "via_stations",
            "route_hint",
            "start_station",
            "end_station",
            "direction",
            "via_station",
            "traveled_at",
            "note",
        ):
            value = getattr(request, field)
            if field in request.model_fields_set and value is not None:
                values[field] = value.strip()
        if "start_station" in request.model_fields_set:
            values["from_station"] = values["start_station"]
        if "end_station" in request.model_fields_set:
            values["to_station"] = values["end_station"]
        if "via_station" in request.model_fields_set:
            values["via_stations"] = values["via_station"]
        if "traveled_at" in request.model_fields_set:
            values["travel_date"] = values["traveled_at"]
        row.normalized_json = _normalized_csv_values(values)
        _resolve_row(db, row)
        if request.selected_candidate_id:
            candidate = next(
                (
                    item
                    for item in row.candidate_json
                    if item["candidate_id"] == request.selected_candidate_id
                ),
                None,
            )
            if candidate is None:
                raise APIError(
                    status_code=409,
                    code="candidate_expired",
                    message="所选候选已失效，请重新审核。",
                )
            if candidate.get("can_commit") is False:
                raise APIError(
                    status_code=409,
                    code="candidate_below_threshold",
                    message="所选铁路候选低于提交阈值，请补充有序站点后重算。",
                )
            row.selected_candidate_id = request.selected_candidate_id
            row.resolution_status = "resolved"
            row.error_code = None
            row.error_message = None
    _refresh_counts(db, batch)
    db.commit()
    db.refresh(row)
    return _row_response(row)


@router.post("/{batch_id}/resolve", response_model=ImportBatchResponse)
def resolve_import_batch(
    batch_id: int, db: Session = Depends(get_db)
) -> ImportBatchResponse:
    batch = _require_batch(db, batch_id)
    if batch.status == "committed":
        raise APIError(
            status_code=409,
            code="batch_already_committed",
            message="已提交批次不能重新解析。",
        )
    _require_reviewable(batch)
    rows = db.scalars(
        select(ImportRow).where(
            ImportRow.batch_id == batch_id,
            ImportRow.resolution_status != "ignored",
        )
    ).all()
    for row in rows:
        _resolve_row(db, row)
    _refresh_counts(db, batch)
    db.commit()
    db.refresh(batch)
    return _batch_response(batch)


def _selected_metro_candidate(db: Session, row: ImportRow) -> ResolvedCandidate:
    if (
        row.matched_line_id is None
        or row.matched_start_station_id is None
        or row.matched_end_station_id is None
        or row.selected_candidate_id is None
    ):
        raise APIError(
            status_code=409,
            code="row_not_resolved",
            message=f"第 {row.row_no} 行尚未解析。",
        )
    values = row.normalized_json
    via_station_ids: list[int] = []
    for via_name in str(values.get("via_station", "")).split("|"):
        if not via_name.strip():
            continue
        via_candidates = exact_line_station_matches(
            db, line_id=row.matched_line_id, value=via_name
        )
        via = _single_match(via_candidates)
        if via is None:
            raise APIError(
                status_code=409,
                code="row_not_resolved",
                message=f"第 {row.row_no} 行途经站已失效。",
            )
        via_station_ids.append(via.id)
    resolution = METRO_PROVIDER.resolve_line(
        db,
        line_id=row.matched_line_id,
        start_station_id=row.matched_start_station_id,
        end_station_id=row.matched_end_station_id,
        direction=str(values.get("direction", "")) or "auto",
        via_station_ids=via_station_ids,
    )
    for candidate in resolution.candidates:
        if candidate.candidate_id == row.selected_candidate_id:
            return candidate
    raise APIError(
        status_code=409,
        code="candidate_expired",
        message=f"第 {row.row_no} 行候选已过期。",
    )


def _selected_rail_candidate(
    db: Session, row: ImportRow
) -> tuple[RailJourneyLegCreate, RailPathCandidate]:
    if (
        row.matched_rail_start_station_id is None
        or row.matched_rail_end_station_id is None
        or row.selected_candidate_id is None
    ):
        raise APIError(
            status_code=409,
            code="row_not_resolved",
            message=f"第 {row.row_no} 行铁路站点尚未解析。",
        )
    selected_item = next(
        (
            item
            for item in row.candidate_json
            if item.get("candidate_id") == row.selected_candidate_id
        ),
        None,
    )
    if selected_item is None or selected_item.get("can_commit") is False:
        raise APIError(
            status_code=409,
            code="candidate_expired",
            message=f"第 {row.row_no} 行铁路候选不可提交或已经过期。",
        )
    values = row.normalized_json
    travel_date = str(values.get("travel_date", "")).strip()
    train_type = _rail_train_type(values)
    if not travel_date or train_type is None:
        raise APIError(
            status_code=409,
            code="row_not_resolved",
            message=f"第 {row.row_no} 行铁路日期或车型缺失。",
        )
    via_ids: list[int] = []
    for via_name in str(values.get("via_stations", "")).split("|"):
        if not via_name.strip():
            continue
        via = _exact_rail_station(db, via_name)
        if via is None:
            raise APIError(
                status_code=409,
                code="row_not_resolved",
                message=f"第 {row.row_no} 行铁路途经站已失效。",
            )
        via_ids.append(via.id)
    facts = CSV_TIMETABLE_PROVIDER.create_facts(
        travel_date=date.fromisoformat(travel_date),
        train_no=str(values.get("train_no", "")).strip() or None,
        train_type=train_type,
        start_station_id=row.matched_rail_start_station_id,
        end_station_id=row.matched_rail_end_station_id,
        via_station_ids=via_ids,
        route_hint=str(values.get("route_hint", "")).strip() or None,
    )
    leg_input = RailJourneyLegCreate(
        mode="rail",
        travel_date=facts.travel_date,
        train_no=facts.train_no,
        train_type=facts.train_type,
        start_station_id=facts.start_station_id,
        end_station_id=facts.end_station_id,
        via_station_ids=list(facts.via_station_ids),
        route_hint=facts.route_hint,
        candidate_id=row.selected_candidate_id,
        candidate_digest=str(selected_item.get("digest", "")),
    )
    try:
        resolution = RAILWAY_PROVIDER.resolve(db, facts)
    except RailResolutionError as error:
        raise APIError(
            status_code=409,
            code=error.code,
            message=f"第 {row.row_no} 行铁路候选重算失败：{error}",
        ) from error
    for candidate in resolution.candidates:
        if (
            candidate.candidate_id == leg_input.candidate_id
            and candidate.digest == leg_input.candidate_digest
            and candidate.can_commit
        ):
            return leg_input, candidate
    raise APIError(
        status_code=409,
        code="candidate_expired",
        message=f"第 {row.row_no} 行铁路候选已经变化，请重新审核。",
    )


@router.post("/{batch_id}/commit", response_model=ImportBatchResponse)
def commit_import_batch(
    batch_id: int,
    request: CommitRequest,
    db: Session = Depends(get_db),
) -> ImportBatchResponse:
    batch = _require_batch(db, batch_id)
    if batch.status == "committed":
        raise APIError(
            status_code=409,
            code="batch_already_committed",
            message="这个 CSV 批次已经提交。",
        )
    _require_reviewable(batch)
    rows = db.scalars(
        select(ImportRow)
        .where(ImportRow.batch_id == batch_id)
        .order_by(ImportRow.row_no)
    ).all()
    pending = [
        row
        for row in rows
        if row.resolution_status not in {"resolved", "ignored", "committed"}
    ]
    if pending and request.strategy == "all":
        raise APIError(
            status_code=409,
            code="batch_needs_review",
            message="仍有未处理行；请修复、确认或忽略后再提交。",
            details={"row_numbers": [row.row_no for row in pending]},
        )
    resolved = [row for row in rows if row.resolution_status == "resolved"]
    if not resolved:
        raise APIError(
            status_code=409,
            code="batch_has_no_resolved_rows",
            message="没有可提交的已解析行。",
        )
    metro_candidates: dict[int, ResolvedCandidate] = {}
    rail_candidates: dict[int, tuple[RailJourneyLegCreate, RailPathCandidate]] = {}
    for row in resolved:
        if row.normalized_json.get("mode") == "rail":
            rail_candidates[row.id] = _selected_rail_candidate(db, row)
        else:
            metro_candidates[row.id] = _selected_metro_candidate(db, row)
    groups: dict[str, list[ImportRow]] = defaultdict(list)
    for row in resolved:
        key = (
            str(row.normalized_json.get("journey_id", "")).strip()
            or f"row-{row.row_no}"
        )
        groups[key].append(row)
    batch.status = "committing"
    try:
        for journey_key, group_rows in groups.items():
            explicit_leg_numbers = [
                int(row.normalized_json["leg_no"])
                for row in group_rows
                if str(row.normalized_json.get("leg_no", "")).strip()
            ]
            if len(explicit_leg_numbers) != len(set(explicit_leg_numbers)):
                raise APIError(
                    status_code=409,
                    code="duplicate_leg_no",
                    message=f"行程 {journey_key} 存在重复 leg_no。",
                )
            ordered = sorted(
                group_rows,
                key=lambda item: int(item.normalized_json.get("leg_no") or item.row_no),
            )
            traveled_values = {
                str(row.normalized_json.get("traveled_at", "")).strip()
                for row in ordered
                if str(row.normalized_json.get("traveled_at", "")).strip()
            }
            if len(traveled_values) > 1:
                raise APIError(
                    status_code=409,
                    code="journey_date_conflict",
                    message=f"行程 {journey_key} 的多个分段日期不一致。",
                )
            first = ordered[0].normalized_json
            traveled = next(iter(traveled_values), "")
            journey = Journey(
                journey_code=f"csv-{batch.id}-{journey_key}"[:120],
                traveled_at=date.fromisoformat(traveled) if traveled else None,
                source_type="csv",
                note=str(first.get("note", "")).strip() or None,
            )
            db.add(journey)
            db.flush()
            for leg_no, row in enumerate(ordered, start=1):
                if row.normalized_json.get("mode") == "rail":
                    leg_input, rail_candidate = rail_candidates[row.id]
                    _save_rail_leg(
                        db,
                        journey_id=journey.id,
                        leg_no=leg_no,
                        leg_input=leg_input,
                        candidate=rail_candidate,
                        timetable_provider="csv",
                    )
                    row.resolution_status = "committed"
                    continue
                candidate = metro_candidates[row.id]
                if (
                    row.matched_city_id is None
                    or row.matched_line_id is None
                    or row.matched_start_station_id is None
                    or row.matched_end_station_id is None
                ):
                    raise APIError(
                        status_code=409,
                        code="row_not_resolved",
                        message=f"第 {row.row_no} 行网络引用缺失。",
                    )
                leg = JourneyLeg(
                    journey_id=journey.id,
                    leg_no=leg_no,
                    dataset_version_id=candidate.dataset_version_id,
                    city_id=row.matched_city_id,
                    line_id=row.matched_line_id,
                    route_variant_id=candidate.route_variant_id,
                    start_station_id=row.matched_start_station_id,
                    end_station_id=row.matched_end_station_id,
                    direction=candidate.direction_name,
                    resolution_status="resolved",
                    resolution_message="CSV 审核提交",
                    candidate_digest=candidate.digest,
                )
                db.add(leg)
                db.flush()
                for order_no, (edge_id, reversed_edge) in enumerate(
                    zip(candidate.edge_ids, candidate.reversed_edges, strict=True),
                    start=1,
                ):
                    db.add(
                        JourneyLegEdge(
                            journey_leg_id=leg.id,
                            route_edge_id=edge_id,
                            order_no=order_no,
                            reversed=reversed_edge,
                        )
                    )
                row.resolution_status = "committed"
        _refresh_counts(db, batch)
        batch.status = "committed"
        batch.committed_at = datetime.now().astimezone()
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise APIError(
            status_code=409,
            code="csv_commit_failed",
            message="CSV 提交失败，未写入任何新行程。",
        ) from error
    except Exception:
        db.rollback()
        raise
    db.refresh(batch)
    return _batch_response(batch)


@router.delete("/{batch_id}", status_code=204)
def delete_import_batch(batch_id: int, db: Session = Depends(get_db)) -> Response:
    batch = _require_batch(db, batch_id)
    if batch.status == "committed":
        raise APIError(
            status_code=409,
            code="batch_already_committed",
            message="已提交批次的审核记录不能删除。",
        )
    db.execute(delete(ImportRow).where(ImportRow.batch_id == batch_id))
    db.delete(batch)
    db.commit()
    return Response(status_code=204)
