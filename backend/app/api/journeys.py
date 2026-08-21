from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pyproj import Geod
from shapely.geometry import LineString
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.paths import RailPathCandidateResponse, rail_candidate_response
from app.core.errors import APIError
from app.db.models import (
    City,
    Journey,
    JourneyLeg,
    JourneyLegEdge,
    Line,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RailJourneyLegDetail,
    RailJourneyStop,
    RailStation,
    RouteEdge,
    Station,
)
from app.db.session import get_db
from app.providers import (
    CSV_TIMETABLE_PROVIDER,
    MANUAL_TIMETABLE_PROVIDER,
    METRO_PROVIDER,
    RAILWAY_PROVIDER,
)
from app.providers.contracts import RailTravelFacts
from app.rail.resolver import (
    RailPathCandidate,
    RailPathResolution,
    RailResolutionError,
    RailTrainType,
    ready_rail_dataset,
)
from app.routing.resolver import ResolvedCandidate

router = APIRouter(prefix="/journeys", tags=["journeys"])
_GEOD = Geod(ellps="WGS84")


class MetroJourneyLegCreate(BaseModel):
    mode: Literal["metro"] = "metro"
    city_id: int = Field(gt=0)
    line_id: int = Field(gt=0)
    start_station_id: int = Field(gt=0)
    end_station_id: int = Field(gt=0)
    direction: str = "auto"
    via_station_ids: list[int] = Field(default_factory=list)
    candidate_id: str = Field(min_length=6, max_length=160)
    candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RailJourneyLegCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["rail"]
    travel_date: date
    train_no: str | None = Field(default=None, min_length=1, max_length=80)
    train_type: RailTrainType = "OTHER"
    start_station_id: int = Field(gt=0)
    end_station_id: int = Field(gt=0)
    via_station_ids: list[int] = Field(default_factory=list, max_length=30)
    route_hint: str | None = Field(default=None, max_length=500)
    candidate_id: str = Field(min_length=6, max_length=160)
    candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


JourneyLegCreate = Annotated[
    MetroJourneyLegCreate | RailJourneyLegCreate,
    Field(discriminator="mode"),
]


class JourneyCreate(BaseModel):
    journey_code: str | None = Field(default=None, min_length=1, max_length=120)
    traveled_at: date | None = None
    source_type: Literal["manual", "map", "csv"] = "manual"
    note: str | None = Field(default=None, max_length=2000)
    legs: list[JourneyLegCreate] = Field(min_length=1, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def default_legacy_leg_modes(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not isinstance(value.get("legs"), list):
            return value
        return {
            **value,
            "legs": [
                {"mode": "metro", **leg}
                if isinstance(leg, dict) and "mode" not in leg
                else leg
                for leg in value["legs"]
            ],
        }


class JourneyPatch(BaseModel):
    traveled_at: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    expected_updated_at: datetime | None = None


class JourneyLegResponse(BaseModel):
    id: int
    leg_no: int
    transport_mode: Literal["metro", "rail"]
    dataset_version_id: int | None
    rail_dataset_version_id: int | None = None
    graph_version: str | None = None
    city_id: int | None
    city_name: str | None
    line_id: int | None
    line_name: str | None
    route_variant_id: int | None
    start_station_id: int | None
    start_station_name: str | None
    end_station_id: int | None
    end_station_name: str | None
    travel_date: date | None = None
    train_no: str | None = None
    train_type: str | None = None
    timetable_provider: str | None = None
    routing_profile: str | None = None
    scoring_version: str | None = None
    route_hint: str | None = None
    score_details: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    via_station_ids: list[int] = Field(default_factory=list)
    osm_way_ids: list[int] = Field(default_factory=list)
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


class RailRecomputeLegPreview(BaseModel):
    leg_no: int
    source_graph_version: str
    target_graph_version: str
    station_names: list[str]
    status: Literal["resolved", "needs_review", "unresolved"]
    candidates: list[RailPathCandidateResponse]


class RailRecomputePreviewResponse(BaseModel):
    journey_id: int
    target_graph_version: str
    target_profile_version: str
    legs: list[RailRecomputeLegPreview]


class RailRecomputeSelection(BaseModel):
    leg_no: int = Field(gt=0)
    candidate_id: str = Field(min_length=6, max_length=160)
    candidate_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class RailRecomputeRequest(BaseModel):
    target_graph_version: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    selections: list[RailRecomputeSelection] = Field(min_length=1, max_length=20)


@dataclass(frozen=True, slots=True)
class _RailRecomputeContext:
    leg: JourneyLeg
    detail: RailJourneyLegDetail
    source_dataset: RailDatasetVersion
    target_dataset: RailDatasetVersion
    facts: RailTravelFacts
    resolution: RailPathResolution
    station_names: tuple[str, ...]


def _journey_code() -> str:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    return f"trip-{timestamp}-{uuid4().hex[:6]}"


def _candidate_for_leg(db: Session, leg: MetroJourneyLegCreate) -> ResolvedCandidate:
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
    resolution = METRO_PROVIDER.resolve_line(
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


def _rail_candidate_for_leg(
    db: Session, leg: RailJourneyLegCreate
) -> RailPathCandidate:
    try:
        facts = MANUAL_TIMETABLE_PROVIDER.create_facts(
            travel_date=leg.travel_date,
            train_no=leg.train_no,
            train_type=leg.train_type,
            start_station_id=leg.start_station_id,
            end_station_id=leg.end_station_id,
            via_station_ids=leg.via_station_ids,
            route_hint=leg.route_hint,
        )
        resolution = RAILWAY_PROVIDER.resolve(db, facts)
    except RailResolutionError as error:
        raise APIError(
            status_code=error.status_code,
            code=error.code,
            message=str(error),
        ) from error
    for candidate in resolution.candidates:
        if (
            candidate.candidate_id == leg.candidate_id
            and candidate.digest == leg.candidate_digest
            and candidate.can_commit
        ):
            return candidate
    raise APIError(
        status_code=409,
        code="candidate_expired",
        message="铁路图、站序或候选路径已经变化，请重新预览并确认。",
    )


def _rail_recompute_context(db: Session, leg: JourneyLeg) -> _RailRecomputeContext:
    detail = db.get(RailJourneyLegDetail, leg.id)
    stop_rows = db.execute(
        select(RailJourneyStop, RailStation)
        .join(RailStation, RailStation.id == RailJourneyStop.station_id)
        .where(RailJourneyStop.journey_leg_id == leg.id)
        .order_by(RailJourneyStop.stop_sequence)
    ).all()
    source_snapshots = db.scalars(
        select(RailJourneyEdgeSnapshot)
        .where(RailJourneyEdgeSnapshot.journey_leg_id == leg.id)
        .order_by(RailJourneyEdgeSnapshot.order_no)
    ).all()
    source_dataset_ids = {
        snapshot.rail_dataset_version_id for snapshot in source_snapshots
    }
    source_dataset = (
        db.get(RailDatasetVersion, next(iter(source_dataset_ids)))
        if len(source_dataset_ids) == 1
        else None
    )
    if detail is None or source_dataset is None or len(stop_rows) < 2:
        raise APIError(
            status_code=500,
            code="journey_reference_missing",
            message="铁路行程缺少可用于重算的站序或版本引用。",
        )
    try:
        target_dataset = ready_rail_dataset(db)
    except RailResolutionError as error:
        raise APIError(
            status_code=error.status_code,
            code=error.code,
            message=str(error),
        ) from error
    mapped_stations: list[RailStation] = []
    for _, source_station in stop_rows:
        target_station = db.scalar(
            select(RailStation).where(
                RailStation.rail_dataset_version_id == target_dataset.id,
                RailStation.osm_type == source_station.osm_type,
                RailStation.osm_id == source_station.osm_id,
                RailStation.match_status == "ready",
            )
        )
        if target_station is None:
            raise APIError(
                status_code=409,
                code="rail_station_remap_required",
                message=(
                    f"车站“{source_station.name_cn}”无法按 OSM 身份映射到当前图；"
                    "请在铁路编辑器中重新选择站点。"
                ),
                details={"leg_no": leg.leg_no, "station_id": source_station.id},
            )
        mapped_stations.append(target_station)
    facts_provider = (
        CSV_TIMETABLE_PROVIDER
        if detail.timetable_provider == "csv"
        else MANUAL_TIMETABLE_PROVIDER
    )
    facts = facts_provider.create_facts(
        travel_date=detail.travel_date,
        train_no=detail.train_no,
        train_type=cast(RailTrainType, detail.train_type),
        start_station_id=mapped_stations[0].id,
        end_station_id=mapped_stations[-1].id,
        via_station_ids=[station.id for station in mapped_stations[1:-1]],
        route_hint=detail.route_hint,
    )
    try:
        resolution = RAILWAY_PROVIDER.resolve(db, facts)
    except RailResolutionError as error:
        raise APIError(
            status_code=error.status_code,
            code=error.code,
            message=str(error),
        ) from error
    return _RailRecomputeContext(
        leg=leg,
        detail=detail,
        source_dataset=source_dataset,
        target_dataset=target_dataset,
        facts=facts,
        resolution=resolution,
        station_names=tuple(station.name_cn for station in mapped_stations),
    )


def _rail_leg_response(db: Session, leg: JourneyLeg) -> JourneyLegResponse:
    detail = db.get(RailJourneyLegDetail, leg.id)
    stop_rows = db.execute(
        select(RailJourneyStop, RailStation)
        .join(RailStation, RailStation.id == RailJourneyStop.station_id)
        .where(RailJourneyStop.journey_leg_id == leg.id)
        .order_by(RailJourneyStop.stop_sequence)
    ).all()
    snapshots = db.scalars(
        select(RailJourneyEdgeSnapshot)
        .where(RailJourneyEdgeSnapshot.journey_leg_id == leg.id)
        .order_by(RailJourneyEdgeSnapshot.order_no)
    ).all()
    dataset = (
        db.get(RailDatasetVersion, snapshots[0].rail_dataset_version_id)
        if snapshots
        else None
    )
    if detail is None or dataset is None or len(stop_rows) < 2 or not snapshots:
        raise APIError(
            status_code=500,
            code="journey_reference_missing",
            message="铁路行程引用的站序或几何快照不完整。",
        )
    stops = [station for _, station in stop_rows]
    return JourneyLegResponse(
        id=leg.id,
        leg_no=leg.leg_no,
        transport_mode="rail",
        dataset_version_id=None,
        rail_dataset_version_id=dataset.id,
        graph_version=dataset.graph_version,
        city_id=None,
        city_name=None,
        line_id=None,
        line_name=None,
        route_variant_id=None,
        start_station_id=stops[0].id,
        start_station_name=stops[0].name_cn,
        end_station_id=stops[-1].id,
        end_station_name=stops[-1].name_cn,
        travel_date=detail.travel_date,
        train_no=detail.train_no,
        train_type=detail.train_type,
        timetable_provider=detail.timetable_provider,
        routing_profile=detail.routing_profile,
        scoring_version=detail.scoring_version,
        route_hint=detail.route_hint,
        score_details=detail.score_details_json,
        warnings=detail.warnings_json,
        via_station_ids=[station.id for station in stops[1:-1]],
        osm_way_ids=[
            snapshot.osm_way_id
            for snapshot in snapshots
            if snapshot.osm_way_id is not None
        ],
        direction=detail.routing_profile,
        resolution_status=leg.resolution_status,
        candidate_digest=leg.candidate_digest,
        edge_ids=[snapshot.id for snapshot in snapshots],
        reversed_edges=[snapshot.reversed for snapshot in snapshots],
        distance_m=sum(snapshot.distance_m for snapshot in snapshots),
    )


def _leg_response(db: Session, leg: JourneyLeg) -> JourneyLegResponse:
    if leg.transport_mode == "rail":
        return _rail_leg_response(db, leg)
    if (
        leg.transport_mode != "metro"
        or leg.dataset_version_id is None
        or leg.city_id is None
        or leg.line_id is None
        or leg.route_variant_id is None
        or leg.start_station_id is None
        or leg.end_station_id is None
    ):
        raise APIError(
            status_code=500,
            code="journey_transport_not_supported",
            message="这条行程包含当前页面尚未支持的交通方式。",
        )
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
        transport_mode="metro",
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


def _save_metro_leg(
    db: Session,
    *,
    journey_id: int,
    leg_no: int,
    leg_input: MetroJourneyLegCreate,
    candidate: ResolvedCandidate,
) -> None:
    leg = JourneyLeg(
        journey_id=journey_id,
        leg_no=leg_no,
        transport_mode="metro",
        dataset_version_id=candidate.dataset_version_id,
        city_id=leg_input.city_id,
        line_id=leg_input.line_id,
        route_variant_id=candidate.route_variant_id,
        start_station_id=leg_input.start_station_id,
        end_station_id=leg_input.end_station_id,
        direction=candidate.direction_name,
        resolution_status="resolved",
        resolution_message=("用户已确认带警告候选" if candidate.warnings else None),
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


def _geodesic_distance(coordinates: list[tuple[float, float]]) -> float:
    distance = 0.0
    for start, end in pairwise(coordinates):
        _, _, segment_distance = _GEOD.inv(*start, *end)
        distance += float(segment_distance)
    return distance


def _save_rail_leg(
    db: Session,
    *,
    journey_id: int,
    leg_no: int,
    leg_input: RailJourneyLegCreate,
    candidate: RailPathCandidate,
    timetable_provider: str = "manual",
) -> None:
    facts_provider = (
        CSV_TIMETABLE_PROVIDER
        if timetable_provider == "csv"
        else MANUAL_TIMETABLE_PROVIDER
    )
    facts = facts_provider.create_facts(
        travel_date=leg_input.travel_date,
        train_no=leg_input.train_no,
        train_type=leg_input.train_type,
        start_station_id=leg_input.start_station_id,
        end_station_id=leg_input.end_station_id,
        via_station_ids=leg_input.via_station_ids,
        route_hint=leg_input.route_hint,
    )
    leg = JourneyLeg(
        journey_id=journey_id,
        leg_no=leg_no,
        transport_mode="rail",
        dataset_version_id=None,
        city_id=None,
        line_id=None,
        route_variant_id=None,
        start_station_id=None,
        end_station_id=None,
        direction=candidate.routing_profile,
        resolution_status="resolved",
        resolution_message=("用户已确认带警告候选" if candidate.warnings else None),
        candidate_digest=candidate.digest,
    )
    db.add(leg)
    db.flush()
    db.add(
        RailJourneyLegDetail(
            journey_leg_id=leg.id,
            travel_date=facts.travel_date,
            train_no=facts.train_no,
            train_type=facts.train_type,
            timetable_provider=facts.timetable_provider,
            routing_profile=candidate.routing_profile,
            scoring_version=candidate.scoring_version,
            route_hint=facts.route_hint,
            confidence=candidate.score,
            score_details_json=list(candidate.score_details),
            warnings_json=list(candidate.warnings),
            selected_candidate_digest=candidate.digest,
        )
    )
    station_ids = [
        leg_input.start_station_id,
        *leg_input.via_station_ids,
        leg_input.end_station_id,
    ]
    stations = [db.get(RailStation, station_id) for station_id in station_ids]
    if any(station is None for station in stations):
        raise APIError(
            status_code=409,
            code="rail_station_expired",
            message="铁路候选引用的车站已经变化，请重新预览。",
        )
    for stop_sequence, station in enumerate(stations, start=1):
        assert station is not None
        db.add(
            RailJourneyStop(
                journey_leg_id=leg.id,
                stop_sequence=stop_sequence,
                station_id=station.id,
                raw_station_name=station.name_cn,
                arrival_time=None,
                departure_time=None,
                is_boarding=stop_sequence == 1,
                is_alighting=stop_sequence == len(stations),
                match_method="user_confirmed",
                match_confidence=1.0,
                locked_by_user=True,
            )
        )
    coordinates = list(candidate.coordinates)
    for order_no, way_range in enumerate(candidate.way_ranges, start=1):
        segment_coordinates = coordinates[
            way_range.start_index : way_range.end_index + 1
        ]
        if len(segment_coordinates) < 2:
            raise APIError(
                status_code=409,
                code="rail_candidate_invalid",
                message="铁路候选的 OSM way 几何范围无效，请重新预览。",
            )
        geometry = LineString(segment_coordinates)
        db.add(
            RailJourneyEdgeSnapshot(
                journey_leg_id=leg.id,
                order_no=order_no,
                rail_dataset_version_id=candidate.rail_dataset_version_id,
                provider_edge_ref=(
                    f"{candidate.routing_profile}:{way_range.osm_way_id}:"
                    f"{way_range.start_index}-{way_range.end_index}"
                ),
                osm_way_id=way_range.osm_way_id,
                from_osm_node_id=None,
                to_osm_node_id=None,
                reversed=False,
                continuity_group=1,
                distance_m=_geodesic_distance(segment_coordinates),
                geometry_wkb=geometry.wkb,
                geometry_sha256=hashlib.sha256(geometry.wkb).hexdigest(),
                min_lon=geometry.bounds[0],
                min_lat=geometry.bounds[1],
                max_lon=geometry.bounds[2],
                max_lat=geometry.bounds[3],
                quality_flags_json=list(candidate.warnings),
            )
        )


def _clone_metro_leg(
    db: Session,
    *,
    journey_id: int,
    source_leg: JourneyLeg,
) -> None:
    if (
        source_leg.transport_mode != "metro"
        or source_leg.dataset_version_id is None
        or source_leg.city_id is None
        or source_leg.line_id is None
        or source_leg.route_variant_id is None
        or source_leg.start_station_id is None
        or source_leg.end_station_id is None
    ):
        raise APIError(
            status_code=500,
            code="journey_reference_missing",
            message="原行程的地铁区间引用不完整，无法安全复制。",
        )
    cloned_leg = JourneyLeg(
        journey_id=journey_id,
        leg_no=source_leg.leg_no,
        transport_mode="metro",
        dataset_version_id=source_leg.dataset_version_id,
        city_id=source_leg.city_id,
        line_id=source_leg.line_id,
        route_variant_id=source_leg.route_variant_id,
        start_station_id=source_leg.start_station_id,
        end_station_id=source_leg.end_station_id,
        direction=source_leg.direction,
        resolution_status=source_leg.resolution_status,
        resolution_message=source_leg.resolution_message,
        candidate_digest=source_leg.candidate_digest,
    )
    db.add(cloned_leg)
    db.flush()
    edge_rows = db.scalars(
        select(JourneyLegEdge)
        .where(JourneyLegEdge.journey_leg_id == source_leg.id)
        .order_by(JourneyLegEdge.order_no)
    ).all()
    if not edge_rows:
        raise APIError(
            status_code=500,
            code="journey_reference_missing",
            message="原行程的地铁几何引用不完整，无法安全复制。",
        )
    for edge in edge_rows:
        db.add(
            JourneyLegEdge(
                journey_leg_id=cloned_leg.id,
                route_edge_id=edge.route_edge_id,
                order_no=edge.order_no,
                reversed=edge.reversed,
            )
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
    rail_dates = {
        leg.travel_date for leg in request.legs if isinstance(leg, RailJourneyLegCreate)
    }
    if len(rail_dates) > 1 or (
        request.traveled_at is not None
        and rail_dates
        and request.traveled_at not in rail_dates
    ):
        raise APIError(
            status_code=422,
            code="journey_date_mismatch",
            message="同一行程中的铁路区间必须使用同一乘车日期。",
        )
    traveled_at = request.traveled_at or (
        next(iter(rail_dates)) if rail_dates else None
    )
    journey = Journey(
        journey_code=request.journey_code or _journey_code(),
        traveled_at=traveled_at,
        source_type=request.source_type,
        note=request.note,
    )
    db.add(journey)
    try:
        db.flush()
        for leg_no, leg_input in enumerate(request.legs, start=1):
            if isinstance(leg_input, MetroJourneyLegCreate):
                _save_metro_leg(
                    db,
                    journey_id=journey.id,
                    leg_no=leg_no,
                    leg_input=leg_input,
                    candidate=_candidate_for_leg(db, leg_input),
                )
            else:
                _save_rail_leg(
                    db,
                    journey_id=journey.id,
                    leg_no=leg_no,
                    leg_input=leg_input,
                    candidate=_rail_candidate_for_leg(db, leg_input),
                    timetable_provider=(
                        "csv" if request.source_type == "csv" else "manual"
                    ),
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


def _journey_legs(db: Session, journey_id: int) -> list[JourneyLeg]:
    return list(
        db.scalars(
            select(JourneyLeg)
            .where(JourneyLeg.journey_id == journey_id)
            .order_by(JourneyLeg.leg_no)
        ).all()
    )


def _rail_recompute_contexts(
    db: Session, journey: Journey
) -> list[_RailRecomputeContext]:
    rail_legs = [
        leg for leg in _journey_legs(db, journey.id) if leg.transport_mode == "rail"
    ]
    if not rail_legs:
        raise APIError(
            status_code=409,
            code="journey_has_no_rail_legs",
            message="这条行程不包含可按铁路图版本重算的区间。",
        )
    return [_rail_recompute_context(db, leg) for leg in rail_legs]


@router.post(
    "/{journey_id}/rail-recompute/preview",
    response_model=RailRecomputePreviewResponse,
)
def preview_rail_recompute(
    journey_id: int,
    db: Session = Depends(get_db),
) -> RailRecomputePreviewResponse:
    journey = _require_journey(db, journey_id)
    contexts = _rail_recompute_contexts(db, journey)
    target_dataset = contexts[0].target_dataset
    return RailRecomputePreviewResponse(
        journey_id=journey.id,
        target_graph_version=target_dataset.graph_version,
        target_profile_version=target_dataset.profile_version,
        legs=[
            RailRecomputeLegPreview(
                leg_no=context.leg.leg_no,
                source_graph_version=context.source_dataset.graph_version,
                target_graph_version=context.target_dataset.graph_version,
                station_names=list(context.station_names),
                status=context.resolution.status,
                candidates=[
                    rail_candidate_response(candidate)
                    for candidate in context.resolution.candidates
                ],
            )
            for context in contexts
        ],
    )


@router.post(
    "/{journey_id}/rail-recompute",
    response_model=JourneyResponse,
    status_code=201,
)
def confirm_rail_recompute(
    journey_id: int,
    request: RailRecomputeRequest,
    db: Session = Depends(get_db),
) -> JourneyResponse:
    source_journey = _require_journey(db, journey_id)
    source_legs = _journey_legs(db, source_journey.id)
    contexts = _rail_recompute_contexts(db, source_journey)
    target_dataset = contexts[0].target_dataset
    if request.target_graph_version != target_dataset.graph_version:
        raise APIError(
            status_code=409,
            code="rail_recompute_version_expired",
            message="当前铁路图版本已变化，请重新预览后确认。",
            details={"current_graph_version": target_dataset.graph_version},
        )
    selections_by_leg = {
        selection.leg_no: selection for selection in request.selections
    }
    expected_leg_nos = {context.leg.leg_no for context in contexts}
    if (
        len(selections_by_leg) != len(request.selections)
        or set(selections_by_leg) != expected_leg_nos
    ):
        raise APIError(
            status_code=422,
            code="rail_recompute_selection_incomplete",
            message="必须为每一个铁路区间且仅选择一个候选路径。",
            details={"rail_leg_nos": sorted(expected_leg_nos)},
        )
    selected_candidates: dict[int, RailPathCandidate] = {}
    for context in contexts:
        selection = selections_by_leg[context.leg.leg_no]
        candidate = next(
            (
                item
                for item in context.resolution.candidates
                if item.candidate_id == selection.candidate_id
                and item.digest == selection.candidate_digest
                and item.can_commit
            ),
            None,
        )
        if candidate is None:
            raise APIError(
                status_code=409,
                code="candidate_expired",
                message="铁路候选路径已经变化，请重新预览并确认。",
                details={"leg_no": context.leg.leg_no},
            )
        selected_candidates[context.leg.leg_no] = candidate
    provenance = (
        f"铁路版本重算自 {source_journey.journey_code}（行程 #{source_journey.id}），"
        f"目标图 {target_dataset.graph_version}；原行程保留不变。"
    )
    note = "\n".join(item for item in (source_journey.note, provenance) if item)
    recomputed = Journey(
        journey_code=_journey_code(),
        traveled_at=source_journey.traveled_at,
        source_type="manual",
        note=note[:2000],
    )
    context_by_leg = {context.leg.leg_no: context for context in contexts}
    db.add(recomputed)
    try:
        db.flush()
        for source_leg in source_legs:
            if source_leg.transport_mode == "metro":
                _clone_metro_leg(db, journey_id=recomputed.id, source_leg=source_leg)
                continue
            context = context_by_leg[source_leg.leg_no]
            facts = context.facts
            _save_rail_leg(
                db,
                journey_id=recomputed.id,
                leg_no=source_leg.leg_no,
                leg_input=RailJourneyLegCreate(
                    mode="rail",
                    travel_date=facts.travel_date,
                    train_no=facts.train_no,
                    train_type=facts.train_type,
                    start_station_id=facts.start_station_id,
                    end_station_id=facts.end_station_id,
                    via_station_ids=list(facts.via_station_ids),
                    route_hint=facts.route_hint,
                    candidate_id=selected_candidates[source_leg.leg_no].candidate_id,
                    candidate_digest=selected_candidates[source_leg.leg_no].digest,
                ),
                candidate=selected_candidates[source_leg.leg_no],
                timetable_provider=context.detail.timetable_provider,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(recomputed)
    return _journey_response(db, recomputed)


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
        if (
            leg.transport_mode != "metro"
            or leg.line_id is None
            or leg.start_station_id is None
            or leg.end_station_id is None
        ):
            raise APIError(
                status_code=409,
                code="rail_reresolve_not_supported",
                message="铁路行程必须从已保存快照重新审核，不能按地铁线路重算。",
                details={"leg_id": leg.id},
            )
        resolution = METRO_PROVIDER.resolve_line(
            db,
            line_id=leg.line_id,
            start_station_id=leg.start_station_id,
            end_station_id=leg.end_station_id,
            direction="auto",
            via_station_ids=[],
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
