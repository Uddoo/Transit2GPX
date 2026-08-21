from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.models import (
    City,
    ImportBatch,
    ImportRow,
    Journey,
    JourneyLeg,
    JourneyLegEdge,
    Line,
    Station,
)
from app.db.session import get_db
from app.matching.names import (
    normalize_city_name,
    normalize_line_name,
)
from app.matching.stations import exact_line_station_matches
from app.routing.resolver import ResolvedCandidate, resolve_line_path

router = APIRouter(prefix="/import-batches", tags=["csv-import"])

REQUIRED_COLUMNS = {"city", "line", "start_station", "end_station"}
KNOWN_COLUMNS = REQUIRED_COLUMNS | {
    "journey_id",
    "leg_no",
    "traveled_at",
    "direction",
    "via_station",
    "note",
}
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
T = TypeVar("T")


class ImportBatchResponse(BaseModel):
    id: int
    filename: str
    encoding: str
    total_rows: int
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
        selected_candidate_id=row.selected_candidate_id,
        candidates=row.candidate_json,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _candidate_json(candidate: ResolvedCandidate) -> dict[str, Any]:
    return {
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


def _single_match(items: Sequence[T]) -> T | None:
    return items[0] if len(items) == 1 else None


def _resolve_row(db: Session, row: ImportRow) -> None:
    values = row.normalized_json
    row.matched_city_id = None
    row.matched_line_id = None
    row.matched_start_station_id = None
    row.matched_end_station_id = None
    row.selected_candidate_id = None
    row.candidate_json = []
    row.error_code = None
    row.error_message = None

    traveled_at = str(values.get("traveled_at", "")).strip()
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

    city_key = normalize_city_name(str(values.get("city", "")))
    cities = [
        city
        for city in db.scalars(select(City).where(City.status == "ready")).all()
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

    resolution = resolve_line_path(
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
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch.id)).all()
    batch.total_rows = len(rows)
    batch.resolved_rows = sum(
        row.resolution_status in {"resolved", "committed"} for row in rows
    )
    batch.review_rows = sum(row.resolution_status == "needs_review" for row in rows)
    batch.failed_rows = sum(row.resolution_status == "unresolved" for row in rows)
    if batch.status not in {"committed", "cancelled"}:
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


@router.get("/template.csv")
def csv_template() -> Response:
    content = (
        "journey_id,leg_no,city,line,start_station,end_station,traveled_at,"
        "direction,via_station,note\r\n"
        "20260820-01,1,上海,2号线,虹桥火车站,人民广场,2026-08-20,,,\r\n"
    )
    return Response(
        content="\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="metro2fog_template.csv"'
        },
    )


@router.post("", response_model=ImportBatchResponse, status_code=201)
async def create_import_batch(
    file: UploadFile = File(),
    db: Session = Depends(get_db),
) -> ImportBatchResponse:
    content = await file.read(MAX_FILE_BYTES + 1)
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
    missing = sorted(REQUIRED_COLUMNS - columns)
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
            normalized = {key: cleaned.get(key, "") for key in KNOWN_COLUMNS}
            row = ImportRow(
                batch_id=batch.id,
                row_no=row_no,
                raw_json=cleaned,
                normalized_json=normalized,
                resolution_status="unresolved",
            )
            db.add(row)
            db.flush()
            _resolve_row(db, row)
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
            "city",
            "line",
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
        row.normalized_json = values
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


def _selected_candidate(db: Session, row: ImportRow) -> ResolvedCandidate:
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
    resolution = resolve_line_path(
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
    candidates = {row.id: _selected_candidate(db, row) for row in resolved}
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
                candidate = candidates[row.id]
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
