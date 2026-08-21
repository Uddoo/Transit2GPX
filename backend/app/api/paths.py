from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.routing.resolver import (
    MultiLineCandidate,
    ResolvedCandidate,
    resolve_city_path,
    resolve_line_path,
)

router = APIRouter(prefix="/paths", tags=["paths"])


class PathPreviewRequest(BaseModel):
    city_id: int = Field(gt=0)
    line_id: int | None = Field(default=None, gt=0)
    start_station_id: int = Field(gt=0)
    end_station_id: int = Field(gt=0)
    direction: str = "auto"
    via_station_ids: list[int] = Field(default_factory=list)


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


class PathPreviewResponse(BaseModel):
    status: Literal["resolved", "needs_review", "unresolved"]
    candidates: list[PathCandidateResponse]


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


@router.post("/preview", response_model=PathPreviewResponse)
def preview_path(
    request: PathPreviewRequest,
    db: Session = Depends(get_db),
) -> PathPreviewResponse:
    if request.line_id is None:
        multi_line_resolution = resolve_city_path(
            db,
            city_id=request.city_id,
            start_station_id=request.start_station_id,
            end_station_id=request.end_station_id,
            via_station_ids=request.via_station_ids,
        )
        return PathPreviewResponse(
            status=multi_line_resolution.status,
            candidates=[
                _multi_line_response(candidate)
                for candidate in multi_line_resolution.candidates
            ],
        )
    resolution = resolve_line_path(
        db,
        line_id=request.line_id,
        start_station_id=request.start_station_id,
        end_station_id=request.end_station_id,
        direction=request.direction,
        via_station_ids=request.via_station_ids,
    )
    return PathPreviewResponse(
        status=resolution.status,
        candidates=[
            _single_line_response(candidate) for candidate in resolution.candidates
        ],
    )
