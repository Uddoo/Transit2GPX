from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.models import (
    City,
    Journey,
    JourneyLeg,
    JourneyLegEdge,
    Line,
    RouteEdge,
    Station,
)
from app.db.session import get_db
from app.routing.resolver import ResolvedCandidate, resolve_line_path

router = APIRouter(prefix="/journeys", tags=["journeys"])


class JourneyLegCreate(BaseModel):
    city_id: int = Field(gt=0)
    line_id: int = Field(gt=0)
    start_station_id: int = Field(gt=0)
    end_station_id: int = Field(gt=0)
    direction: str = "auto"
    via_station_ids: list[int] = Field(default_factory=list)
    candidate_id: str = Field(min_length=6, max_length=160)
    candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class JourneyCreate(BaseModel):
    journey_code: str | None = Field(default=None, min_length=1, max_length=120)
    traveled_at: date | None = None
    source_type: Literal["manual", "map", "csv"] = "manual"
    note: str | None = Field(default=None, max_length=2000)
    legs: list[JourneyLegCreate] = Field(min_length=1, max_length=20)


class JourneyPatch(BaseModel):
    traveled_at: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    expected_updated_at: datetime | None = None


class JourneyLegResponse(BaseModel):
    id: int
    leg_no: int
    dataset_version_id: int
    city_id: int
    city_name: str
    line_id: int
    line_name: str
    route_variant_id: int
    start_station_id: int
    start_station_name: str
    end_station_id: int
    end_station_name: str
    direction: str | None
    resolution_status: str
    candidate_digest: str
    edge_ids: list[int]
    reversed_edges: list[bool]
    distance_m: float


class JourneyResponse(BaseModel):
    id: int
    journey_code: str
    traveled_at: date | None
    source_type: str
    note: str | None
    created_at: datetime
    updated_at: datetime
    distance_m: float
    legs: list[JourneyLegResponse]


class JourneyListResponse(BaseModel):
    items: list[JourneyResponse]
    total: int


def _journey_code() -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"trip-{timestamp}-{uuid4().hex[:6]}"


def _candidate_for_leg(db: Session, leg: JourneyLegCreate) -> ResolvedCandidate:
    line = db.get(Line, leg.line_id)
    start = db.get(Station, leg.start_station_id)
    end = db.get(Station, leg.end_station_id)
    if (
        line is None
        or line.city_id != leg.city_id
        or start is None
        or start.city_id != leg.city_id
        or end is None
        or end.city_id != leg.city_id
    ):
        raise APIError(
            status_code=422,
            code="journey_network_mismatch",
            message="城市、线路和站点不属于同一可用网络。",
        )
    resolution = resolve_line_path(
        db,
        line_id=leg.line_id,
        start_station_id=leg.start_station_id,
        end_station_id=leg.end_station_id,
        direction=leg.direction,
        via_station_ids=leg.via_station_ids,
    )
    for candidate in resolution.candidates:
        if (
            candidate.candidate_id == leg.candidate_id
            and candidate.digest == leg.candidate_digest
        ):
            return candidate
    raise APIError(
        status_code=409,
        code="candidate_expired",
        message="线路数据或候选路径已经变化，请重新预览并确认。",
    )


def _leg_response(db: Session, leg: JourneyLeg) -> JourneyLegResponse:
    city = db.get(City, leg.city_id)
    line = db.get(Line, leg.line_id)
    start = db.get(Station, leg.start_station_id)
    end = db.get(Station, leg.end_station_id)
    edge_rows = db.execute(
        select(JourneyLegEdge, RouteEdge.distance_m)
        .join(RouteEdge, RouteEdge.id == JourneyLegEdge.route_edge_id)
        .where(JourneyLegEdge.journey_leg_id == leg.id)
        .order_by(JourneyLegEdge.order_no)
    ).all()
    if city is None or line is None or start is None or end is None:
        raise APIError(
            status_code=500,
            code="journey_reference_missing",
            message="行程引用的线路数据不完整。",
        )
    return JourneyLegResponse(
        id=leg.id,
        leg_no=leg.leg_no,
        dataset_version_id=leg.dataset_version_id,
        city_id=leg.city_id,
        city_name=city.name_cn,
        line_id=leg.line_id,
        line_name=line.name_cn,
        route_variant_id=leg.route_variant_id,
        start_station_id=leg.start_station_id,
        start_station_name=start.name_cn,
        end_station_id=leg.end_station_id,
        end_station_name=end.name_cn,
        direction=leg.direction,
        resolution_status=leg.resolution_status,
        candidate_digest=leg.candidate_digest,
        edge_ids=[edge.route_edge_id for edge, _ in edge_rows],
        reversed_edges=[edge.reversed for edge, _ in edge_rows],
        distance_m=sum(distance for _, distance in edge_rows),
    )


def _journey_response(db: Session, journey: Journey) -> JourneyResponse:
    legs = db.scalars(
        select(JourneyLeg)
        .where(JourneyLeg.journey_id == journey.id)
        .order_by(JourneyLeg.leg_no)
    ).all()
    leg_responses = [_leg_response(db, leg) for leg in legs]
    return JourneyResponse(
        id=journey.id,
        journey_code=journey.journey_code,
        traveled_at=journey.traveled_at,
        source_type=journey.source_type,
        note=journey.note,
        created_at=journey.created_at,
        updated_at=journey.updated_at,
        distance_m=sum(leg.distance_m for leg in leg_responses),
        legs=leg_responses,
    )


@router.get("", response_model=JourneyListResponse)
def list_journeys(
    city_id: int | None = None,
    line_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> JourneyListResponse:
    if limit < 1 or limit > 500 or offset < 0:
        raise APIError(
            status_code=422,
            code="invalid_pagination",
            message="分页参数超出允许范围。",
        )
    statement = select(Journey).order_by(Journey.traveled_at.desc(), Journey.id.desc())
    if city_id is not None or line_id is not None:
        statement = statement.join(JourneyLeg)
        if city_id is not None:
            statement = statement.where(JourneyLeg.city_id == city_id)
        if line_id is not None:
            statement = statement.where(JourneyLeg.line_id == line_id)
        statement = statement.distinct()
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            Journey.journey_code.ilike(pattern) | Journey.note.ilike(pattern)
        )
    journeys = db.scalars(statement.offset(offset).limit(limit)).all()
    count_statement = select(func.count()).select_from(
        statement.order_by(None).subquery()
    )
    total = int(db.scalar(count_statement) or 0)
    return JourneyListResponse(
        items=[_journey_response(db, journey) for journey in journeys], total=total
    )


@router.post("", response_model=JourneyResponse, status_code=201)
def create_journey(
    request: JourneyCreate,
    db: Session = Depends(get_db),
) -> JourneyResponse:
    candidates = [_candidate_for_leg(db, leg) for leg in request.legs]
    journey = Journey(
        journey_code=request.journey_code or _journey_code(),
        traveled_at=request.traveled_at,
        source_type=request.source_type,
        note=request.note,
    )
    db.add(journey)
    try:
        db.flush()
        for leg_no, (leg_input, candidate) in enumerate(
            zip(request.legs, candidates, strict=True), start=1
        ):
            leg = JourneyLeg(
                journey_id=journey.id,
                leg_no=leg_no,
                dataset_version_id=candidate.dataset_version_id,
                city_id=leg_input.city_id,
                line_id=leg_input.line_id,
                route_variant_id=candidate.route_variant_id,
                start_station_id=leg_input.start_station_id,
                end_station_id=leg_input.end_station_id,
                direction=candidate.direction_name,
                resolution_status="resolved",
                resolution_message=(
                    "用户已确认带警告候选" if candidate.warnings else None
                ),
                candidate_digest=candidate.digest,
            )
            db.add(leg)
            db.flush()
            for order_no, (edge_id, reversed_edge) in enumerate(
                zip(candidate.edge_ids, candidate.reversed_edges, strict=True), start=1
            ):
                db.add(
                    JourneyLegEdge(
                        journey_leg_id=leg.id,
                        route_edge_id=edge_id,
                        order_no=order_no,
                        reversed=reversed_edge,
                    )
                )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(journey)
    return _journey_response(db, journey)


def _require_journey(db: Session, journey_id: int) -> Journey:
    journey = db.get(Journey, journey_id)
    if journey is None:
        raise APIError(
            status_code=404,
            code="journey_not_found",
            message="没有找到这条行程。",
        )
    return journey


@router.get("/{journey_id}", response_model=JourneyResponse)
def get_journey(journey_id: int, db: Session = Depends(get_db)) -> JourneyResponse:
    return _journey_response(db, _require_journey(db, journey_id))


@router.patch("/{journey_id}", response_model=JourneyResponse)
def patch_journey(
    journey_id: int,
    request: JourneyPatch,
    db: Session = Depends(get_db),
) -> JourneyResponse:
    journey = _require_journey(db, journey_id)
    if request.expected_updated_at is not None:
        expected = request.expected_updated_at
        if expected.tzinfo is not None:
            expected = expected.astimezone(UTC).replace(tzinfo=None)
        actual = journey.updated_at
        if actual.tzinfo is not None:
            actual = actual.astimezone(UTC).replace(tzinfo=None)
        if expected != actual:
            raise APIError(
                status_code=409,
                code="journey_update_conflict",
                message="行程已在其他操作中更新，请刷新后重试。",
                details={"updated_at": journey.updated_at.isoformat()},
            )
    fields = request.model_fields_set
    if "traveled_at" in fields:
        journey.traveled_at = request.traveled_at
    if "note" in fields:
        journey.note = request.note
    journey.updated_at = datetime.now().astimezone()
    db.commit()
    db.refresh(journey)
    return _journey_response(db, journey)


@router.delete("/{journey_id}", status_code=204)
def delete_journey(journey_id: int, db: Session = Depends(get_db)) -> Response:
    journey = _require_journey(db, journey_id)
    db.delete(journey)
    db.commit()
    return Response(status_code=204)


@router.post("/{journey_id}/re-resolve", response_model=JourneyResponse)
def re_resolve_journey(
    journey_id: int,
    db: Session = Depends(get_db),
) -> JourneyResponse:
    journey = _require_journey(db, journey_id)
    legs = db.scalars(
        select(JourneyLeg)
        .where(JourneyLeg.journey_id == journey.id)
        .order_by(JourneyLeg.leg_no)
    ).all()
    replacements: list[tuple[JourneyLeg, ResolvedCandidate]] = []
    for leg in legs:
        resolution = resolve_line_path(
            db,
            line_id=leg.line_id,
            start_station_id=leg.start_station_id,
            end_station_id=leg.end_station_id,
            direction="auto",
        )
        if resolution.status != "resolved" or len(resolution.candidates) != 1:
            raise APIError(
                status_code=409,
                code="path_needs_review",
                message="重算得到多个候选，需要回到编辑器人工确认。",
                details={"leg_id": leg.id},
            )
        replacements.append((leg, resolution.candidates[0]))
    try:
        for leg, candidate in replacements:
            db.execute(
                delete(JourneyLegEdge).where(JourneyLegEdge.journey_leg_id == leg.id)
            )
            leg.dataset_version_id = candidate.dataset_version_id
            leg.route_variant_id = candidate.route_variant_id
            leg.direction = candidate.direction_name
            leg.candidate_digest = candidate.digest
            leg.resolution_status = "resolved"
            leg.resolution_message = None
            for order_no, (edge_id, reversed_edge) in enumerate(
                zip(candidate.edge_ids, candidate.reversed_edges, strict=True), start=1
            ):
                db.add(
                    JourneyLegEdge(
                        journey_leg_id=leg.id,
                        route_edge_id=edge_id,
                        order_no=order_no,
                        reversed=reversed_edge,
                    )
                )
        journey.updated_at = datetime.now().astimezone()
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(journey)
    return _journey_response(db, journey)
