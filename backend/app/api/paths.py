from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.session import get_db
from app.providers import MANUAL_TIMETABLE_PROVIDER, METRO_PROVIDER, RAILWAY_PROVIDER
from app.rail.resolver import (
    RailPathCandidate,
    RailResolutionError,
    RailTrainType,
)
from app.routing.resolver import (
    MultiLineCandidate,
    ResolvedCandidate,
)

router = APIRouter(prefix="/paths", tags=["paths"])


class MetroPathPreviewRequest(BaseModel):
    mode: Literal["metro"] = "metro"
    city_id: int = Field(gt=0)
    line_id: int | None = Field(default=None, gt=0)
    start_station_id: int = Field(gt=0)
    end_station_id: int = Field(gt=0)
    direction: str = "auto"
    via_station_ids: list[int] = Field(default_factory=list)


class RailPathPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["rail"]
    travel_date: date
    train_no: str | None = Field(default=None, min_length=1, max_length=80)
    train_type: RailTrainType = "OTHER"
    start_station_id: int = Field(gt=0)
    end_station_id: int = Field(gt=0)
    via_station_ids: list[int] = Field(default_factory=list, max_length=30)
    route_hint: str | None = Field(default=None, max_length=500)


PathPreviewRequestUnion = Annotated[
    MetroPathPreviewRequest | RailPathPreviewRequest,
    Field(discriminator="mode"),
]


class PathPreviewRequest(RootModel[PathPreviewRequestUnion]):
    @model_validator(mode="before")
    @classmethod
    def default_legacy_mode(cls, value: Any) -> Any:
        if isinstance(value, dict) and "mode" not in value:
            return {"mode": "metro", **value}
        return value


class PathLegCandidateResponse(BaseModel):
    candidate_id: str
    digest: str
    dataset_version_id: int
    line_id: int
    route_variant_id: int
    line_name: str
    direction_name: str
    distance_m: float
    start_station_id: int
    end_station_id: int
    station_ids: list[int]
    edge_ids: list[int]
    reversed_edges: list[bool]
    warnings: list[dict[str, Any]]


class PathCandidateResponse(BaseModel):
    mode: Literal["metro"] = "metro"
    candidate_id: str
    digest: str
    dataset_version_id: int
    route_variant_id: int | None
    line_name: str
    direction_name: str
    distance_m: float
    station_count: int
    station_ids: list[int]
    edge_ids: list[int]
    reversed_edges: list[bool]
    geometry: dict[str, Any]
    warnings: list[dict[str, Any]]
    legs: list[PathLegCandidateResponse]


class RailWayRangeResponse(BaseModel):
    start_index: int
    end_index: int
    osm_way_id: int


class RailPathCandidateResponse(BaseModel):
    mode: Literal["rail"] = "rail"
    candidate_id: str
    digest: str
    rail_dataset_version_id: int
    graph_version: str
    profile_version: str
    scoring_version: str
    routing_profile: str
    distance_m: float
    duration_ms: int
    station_count: int
    station_ids: list[int]
    geometry: dict[str, Any]
    way_ranges: list[RailWayRangeResponse]
    score: float
    score_details: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    can_commit: bool


class PathPreviewResponse(BaseModel):
    status: Literal["resolved", "needs_review", "unresolved"]
    candidates: list[PathCandidateResponse | RailPathCandidateResponse]


def _leg_response(candidate: ResolvedCandidate) -> PathLegCandidateResponse:
    return PathLegCandidateResponse(
        candidate_id=candidate.candidate_id,
        digest=candidate.digest,
        dataset_version_id=candidate.dataset_version_id,
        line_id=candidate.line_id,
        route_variant_id=candidate.route_variant_id,
        line_name=candidate.line_name,
        direction_name=candidate.direction_name,
        distance_m=candidate.distance_m,
        start_station_id=candidate.station_ids[0],
        end_station_id=candidate.station_ids[-1],
        station_ids=list(candidate.station_ids),
        edge_ids=list(candidate.edge_ids),
        reversed_edges=list(candidate.reversed_edges),
        warnings=list(candidate.warnings),
    )


def _single_line_response(candidate: ResolvedCandidate) -> PathCandidateResponse:
    return PathCandidateResponse(
        candidate_id=candidate.candidate_id,
        digest=candidate.digest,
        dataset_version_id=candidate.dataset_version_id,
        route_variant_id=candidate.route_variant_id,
        line_name=candidate.line_name,
        direction_name=candidate.direction_name,
        distance_m=candidate.distance_m,
        station_count=len(candidate.station_ids),
        station_ids=list(candidate.station_ids),
        edge_ids=list(candidate.edge_ids),
        reversed_edges=list(candidate.reversed_edges),
        geometry={"type": "LineString", "coordinates": candidate.coordinates},
        warnings=list(candidate.warnings),
        legs=[_leg_response(candidate)],
    )


def _multi_line_response(candidate: MultiLineCandidate) -> PathCandidateResponse:
    return PathCandidateResponse(
        candidate_id=candidate.candidate_id,
        digest=candidate.digest,
        dataset_version_id=candidate.legs[0].dataset_version_id,
        route_variant_id=None,
        line_name=candidate.line_name,
        direction_name=candidate.direction_name,
        distance_m=candidate.distance_m,
        station_count=len(candidate.station_ids),
        station_ids=list(candidate.station_ids),
        edge_ids=[edge_id for leg in candidate.legs for edge_id in leg.edge_ids],
        reversed_edges=[
            reversed_edge
            for leg in candidate.legs
            for reversed_edge in leg.reversed_edges
        ],
        geometry={"type": "LineString", "coordinates": candidate.coordinates},
        warnings=list(candidate.warnings),
        legs=[_leg_response(leg) for leg in candidate.legs],
    )


def rail_candidate_response(candidate: RailPathCandidate) -> RailPathCandidateResponse:
    return RailPathCandidateResponse(
        candidate_id=candidate.candidate_id,
        digest=candidate.digest,
        rail_dataset_version_id=candidate.rail_dataset_version_id,
        graph_version=candidate.graph_version,
        profile_version=candidate.profile_version,
        scoring_version=candidate.scoring_version,
        routing_profile=candidate.routing_profile,
        distance_m=candidate.distance_m,
        duration_ms=candidate.duration_ms,
        station_count=len(candidate.station_ids),
        station_ids=list(candidate.station_ids),
        geometry={"type": "LineString", "coordinates": candidate.coordinates},
        way_ranges=[
            RailWayRangeResponse(
                start_index=way_range.start_index,
                end_index=way_range.end_index,
                osm_way_id=way_range.osm_way_id,
            )
            for way_range in candidate.way_ranges
        ],
        score=candidate.score,
        score_details=list(candidate.score_details),
        warnings=list(candidate.warnings),
        can_commit=candidate.can_commit,
    )


@router.post("/preview", response_model=PathPreviewResponse)
def preview_path(
    request: PathPreviewRequest,
    db: Session = Depends(get_db),
) -> PathPreviewResponse:
    payload = request.root
    if isinstance(payload, RailPathPreviewRequest):
        try:
            facts = MANUAL_TIMETABLE_PROVIDER.create_facts(
                travel_date=payload.travel_date,
                train_no=payload.train_no,
                train_type=payload.train_type,
                start_station_id=payload.start_station_id,
                end_station_id=payload.end_station_id,
                via_station_ids=payload.via_station_ids,
                route_hint=payload.route_hint,
            )
            rail_resolution = RAILWAY_PROVIDER.resolve(db, facts)
        except RailResolutionError as error:
            raise APIError(
                status_code=error.status_code,
                code=error.code,
                message=str(error),
            ) from error
        return PathPreviewResponse(
            status=rail_resolution.status,
            candidates=[
                rail_candidate_response(candidate)
                for candidate in rail_resolution.candidates
            ],
        )
    if payload.line_id is None:
        multi_line_resolution = METRO_PROVIDER.resolve_city(
            db,
            city_id=payload.city_id,
            start_station_id=payload.start_station_id,
            end_station_id=payload.end_station_id,
            via_station_ids=payload.via_station_ids,
        )
        return PathPreviewResponse(
            status=multi_line_resolution.status,
            candidates=[
                _multi_line_response(candidate)
                for candidate in multi_line_resolution.candidates
            ],
        )
    metro_resolution = METRO_PROVIDER.resolve_line(
        db,
        line_id=payload.line_id,
        start_station_id=payload.start_station_id,
        end_station_id=payload.end_station_id,
        direction=payload.direction,
        via_station_ids=payload.via_station_ids,
    )
    return PathPreviewResponse(
        status=metro_resolution.status,
        candidates=[
            _single_line_response(candidate)
            for candidate in metro_resolution.candidates
        ],
    )
