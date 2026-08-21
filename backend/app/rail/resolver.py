from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import RailDatasetVersion, RailStation
from app.rail.importer import RailImportError, load_graph_metadata
from app.rail.sidecar import (
    RailRoutePath,
    RailSidecarError,
    RailWayRange,
    fetch_sidecar_info,
    fetch_sidecar_route,
)

RailTrainType = Literal["G", "C", "D", "Z", "T", "K", "Y", "S", "OTHER"]
RAIL_SCORING_VERSION = "2026-08-21-r0.2"


class RailResolutionError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RailPathCandidate:
    candidate_id: str
    digest: str
    rail_dataset_version_id: int
    graph_version: str
    profile_version: str
    scoring_version: str
    routing_profile: str
    distance_m: float
    duration_ms: int
    station_ids: tuple[int, ...]
    coordinates: tuple[tuple[float, float], ...]
    way_ranges: tuple[RailWayRange, ...]
    score: float
    score_details: tuple[dict[str, Any], ...]
    warnings: tuple[dict[str, Any], ...]
    can_commit: bool


@dataclass(frozen=True, slots=True)
class RailPathResolution:
    status: Literal["resolved", "needs_review", "unresolved"]
    candidates: tuple[RailPathCandidate, ...]


def _profiles(train_type: RailTrainType) -> tuple[str, str, str]:
    if train_type in {"G", "C"}:
        return ("china_high_speed", "china_emu", "china_conventional")
    if train_type in {"D", "S"}:
        return ("china_emu", "china_high_speed", "china_conventional")
    return ("china_conventional", "china_emu", "china_high_speed")


def ready_rail_dataset(db: Session) -> RailDatasetVersion:
    settings = get_settings()
    if not settings.rail_enabled or not settings.rail_graph_version:
        raise RailResolutionError("rail_not_configured", "铁路路径功能尚未配置。", 503)
    actual_graph_version = settings.rail_graph_version
    if actual_graph_version == "active":
        try:
            metadata = load_graph_metadata(
                settings.resolved_rail_graph_root, actual_graph_version
            )
        except RailImportError as error:
            raise RailResolutionError(
                "rail_graph_version_mismatch", "当前铁路图版本元数据无效。", 409
            ) from error
        actual_graph_version = str(metadata["graph_version"])
    dataset = db.scalar(
        select(RailDatasetVersion).where(
            RailDatasetVersion.graph_version == actual_graph_version,
            RailDatasetVersion.status == "ready",
        )
    )
    if dataset is None:
        raise RailResolutionError(
            "rail_graph_version_mismatch",
            "当前铁路图版本没有对应的就绪数据记录。",
            409,
        )
    return dataset


def _verify_sidecar_identity(dataset: RailDatasetVersion) -> None:
    settings = get_settings()
    try:
        sidecar = fetch_sidecar_info(
            settings.rail_sidecar_url, settings.rail_sidecar_timeout_seconds
        )
    except RailSidecarError as error:
        raise RailResolutionError(error.code, str(error), 503) from error
    expected = (
        dataset.graph_version,
        dataset.pbf_checksum,
        dataset.profile_version,
        dataset.openrailrouting_version,
    )
    actual = (
        sidecar.graph_version,
        sidecar.pbf_sha256,
        sidecar.profile_version,
        sidecar.openrailrouting_commit,
    )
    if actual != expected:
        raise RailResolutionError(
            "rail_sidecar_graph_version_mismatch",
            "运行中的铁路路径服务与所选图、PBF 或 Profile 版本不一致。",
            409,
        )


def _ordered_stations(
    db: Session, dataset_id: int, station_ids: list[int]
) -> tuple[RailStation, ...]:
    stations = db.scalars(
        select(RailStation).where(
            RailStation.id.in_(station_ids),
            RailStation.rail_dataset_version_id == dataset_id,
            RailStation.match_status == "ready",
        )
    ).all()
    by_id = {station.id: station for station in stations}
    if len(station_ids) < 2 or any(
        station_id not in by_id for station_id in station_ids
    ):
        raise RailResolutionError(
            "rail_station_version_mismatch",
            "铁路站点不存在、未通过审核或不属于当前图版本。",
            422,
        )
    if any(
        first_station_id == second_station_id
        for first_station_id, second_station_id in pairwise(station_ids)
    ):
        raise RailResolutionError(
            "rail_station_order_invalid", "相邻有序站点不能相同。", 422
        )
    return tuple(by_id[station_id] for station_id in station_ids)


def _coordinate_distance_m(
    coordinates: tuple[tuple[float, float], ...],
    start_index: int = 0,
    end_index: int | None = None,
) -> float:
    if end_index is None:
        end_index = len(coordinates) - 1
    distance = 0.0
    earth_radius_m = 6_371_008.8
    for first, second in pairwise(coordinates[start_index : end_index + 1]):
        first_lon, first_lat = map(math.radians, first)
        second_lon, second_lat = map(math.radians, second)
        delta_lon = second_lon - first_lon
        delta_lat = second_lat - first_lat
        haversine = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lon / 2) ** 2
        )
        distance += earth_radius_m * 2 * math.asin(min(1.0, math.sqrt(haversine)))
    return distance


def _attribute_fraction(
    route: RailRoutePath,
    attribute: str,
    predicate: Any,
) -> tuple[float | None, float]:
    total_distance = _coordinate_distance_m(route.coordinates)
    if total_distance <= 0:
        return None, 0.0
    covered_distance = 0.0
    matching_distance = 0.0
    for item in route.attribute_ranges:
        if item.attribute != attribute or item.value is None:
            continue
        item_distance = _coordinate_distance_m(
            route.coordinates, item.start_index, item.end_index
        )
        covered_distance += item_distance
        if predicate(item.value):
            matching_distance += item_distance
    if covered_distance <= 0:
        return None, 0.0
    return (
        min(1.0, matching_distance / total_distance),
        min(1.0, covered_distance / total_distance),
    )


def _distance_rationality(
    route: RailRoutePath, station_coordinates: tuple[tuple[float, float], ...]
) -> tuple[float, float]:
    direct_distance = sum(
        _coordinate_distance_m((first, second))
        for first, second in pairwise(station_coordinates)
    )
    if direct_distance <= 0:
        return 0.5, 0.0
    ratio = max(1.0, route.distance_m / direct_distance)
    if ratio <= 1.35:
        score = 1.0
    elif ratio <= 1.75:
        score = 0.85
    elif ratio <= 2.25:
        score = 0.65
    else:
        score = 0.4
    return score, ratio


def _candidate(
    *,
    dataset: RailDatasetVersion,
    travel_date: date,
    train_no: str | None,
    train_type: RailTrainType,
    route_hint: str | None,
    station_ids: list[int],
    station_coordinates: tuple[tuple[float, float], ...],
    profile_rank: int,
    route: RailRoutePath,
) -> RailPathCandidate:
    geometry_payload = [list(coordinate) for coordinate in route.coordinates]
    geometry_sha256 = hashlib.sha256(
        json.dumps(geometry_payload, separators=(",", ":")).encode()
    ).hexdigest()
    profile_score = (1.0, 0.82, 0.68)[profile_rank]
    mainline_ratio, mainline_coverage = _attribute_fraction(
        route,
        "railway_service",
        lambda value: value == "none",
    )
    rail_ratio, rail_coverage = _attribute_fraction(
        route,
        "railway_class",
        lambda value: value == "rail",
    )
    electrified_ratio, electrified_coverage = _attribute_fraction(
        route,
        "electrified",
        lambda value: value in {"contact_line", "rail"},
    )
    speed_threshold = 200.0 if train_type in {"G", "C"} else 160.0
    speed_fractions = [
        _attribute_fraction(
            route,
            attribute,
            lambda value: (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and float(value) >= speed_threshold
            ),
        )
        for attribute in ("max_speed", "rail_average_speed")
    ]
    available_speed_fractions = [
        (ratio, coverage) for ratio, coverage in speed_fractions if ratio is not None
    ]
    speed_ratio, speed_coverage = (
        max(available_speed_fractions, key=lambda item: (item[1], item[0]))
        if available_speed_fractions
        else (None, 0.0)
    )
    mainline_score = 0.75 if mainline_ratio is None else 0.5 + mainline_ratio * 0.5
    rail_score = 0.75 if rail_ratio is None else 0.5 + rail_ratio * 0.5
    if train_type in {"G", "C", "D", "S"}:
        speed_score = 0.75 if speed_ratio is None else 0.4 + speed_ratio * 0.6
        electrified_score = (
            0.75 if electrified_ratio is None else 0.5 + electrified_ratio * 0.5
        )
        train_compatibility_score = speed_score * 0.8 + electrified_score * 0.2
    else:
        train_compatibility_score = mainline_score
    distance_score, distance_ratio = _distance_rationality(route, station_coordinates)
    weighted_components = (
        (profile_score, 0.25),
        (1.0, 0.20),
        (train_compatibility_score, 0.20),
        (mainline_score, 0.15),
        (rail_score, 0.05),
        (distance_score, 0.15),
    )
    score = round(sum(value * weight for value, weight in weighted_components), 3)
    score_details: list[dict[str, Any]] = [
        {
            "code": "train_profile_preference",
            "score": round(profile_score, 3),
            "weight": 0.25,
            "profile": route.profile,
            "train_type": train_type,
        },
        {
            "code": "ordered_stations",
            "score": 1.0,
            "weight": 0.20,
            "station_count": len(station_ids),
        },
        {
            "code": "train_compatibility",
            "score": round(train_compatibility_score, 3),
            "weight": 0.20,
            "speed_threshold_kmh": speed_threshold,
            "speed_ratio": None if speed_ratio is None else round(speed_ratio, 3),
            "speed_coverage": round(speed_coverage, 3),
            "electrified_ratio": (
                None if electrified_ratio is None else round(electrified_ratio, 3)
            ),
            "electrified_coverage": round(electrified_coverage, 3),
        },
        {
            "code": "mainline_ratio",
            "score": round(mainline_score, 3),
            "weight": 0.15,
            "ratio": None if mainline_ratio is None else round(mainline_ratio, 3),
            "coverage": round(mainline_coverage, 3),
        },
        {
            "code": "railway_class",
            "score": round(rail_score, 3),
            "weight": 0.05,
            "rail_ratio": None if rail_ratio is None else round(rail_ratio, 3),
            "coverage": round(rail_coverage, 3),
        },
        {
            "code": "osm_route_relation",
            "score": None,
            "weight": 0.0,
            "status": "not_exposed_by_sidecar",
            "route_hint": route_hint,
        },
        {
            "code": "distance_rationality",
            "score": round(distance_score, 3),
            "weight": 0.15,
            "route_to_direct_ratio": round(distance_ratio, 3),
        },
        {
            "code": "scoring_version",
            "score": score,
            "weight": 1.0,
            "version": RAIL_SCORING_VERSION,
        },
    ]
    warnings: list[dict[str, Any]] = []
    missing_attributes = [
        name
        for name, coverage in (
            ("speed", speed_coverage),
            ("electrified", electrified_coverage),
            ("railway_service", mainline_coverage),
            ("railway_class", rail_coverage),
        )
        if coverage < 0.5
    ]
    if missing_attributes:
        warnings.append(
            {
                "code": "rail_attributes_incomplete",
                "message": "部分 OSM 铁路属性覆盖不足，评分已按中性值处理。",
                "attributes": missing_attributes,
            }
        )
    if mainline_ratio is not None and mainline_ratio < 0.80:
        warnings.append(
            {
                "code": "rail_service_segments",
                "message": "候选包含较多 siding、yard、spur 或 crossover 区段。",
                "mainline_ratio": round(mainline_ratio, 3),
            }
        )
    if (
        train_type in {"G", "C", "D", "S"}
        and speed_ratio is not None
        and speed_ratio < 0.60
    ):
        warnings.append(
            {
                "code": "train_infrastructure_low_compatibility",
                "message": "候选中符合该动车组速度偏好的区段占比较低。",
                "speed_ratio": round(speed_ratio, 3),
            }
        )
    if distance_score < 0.70:
        warnings.append(
            {
                "code": "rail_distance_detour",
                "message": "候选距离相对站间直线距离偏大，请核对站序和线路。",
                "route_to_direct_ratio": round(distance_ratio, 3),
            }
        )
    if route_hint:
        warnings.append(
            {
                "code": "route_hint_not_authoritative",
                "message": "线路提示用于人工核对，首版不把它当作时刻表事实。",
                "route_hint": route_hint,
            }
        )
    digest_payload = {
        "mode": "rail",
        "travel_date": travel_date.isoformat(),
        "train_no": train_no,
        "train_type": train_type,
        "route_hint": route_hint,
        "rail_dataset_version_id": dataset.id,
        "graph_version": dataset.graph_version,
        "profile_version": dataset.profile_version,
        "routing_profile": route.profile,
        "station_ids": station_ids,
        "geometry_sha256": geometry_sha256,
        "osm_way_ids": [way_range.osm_way_id for way_range in route.way_ranges],
        "scoring_version": RAIL_SCORING_VERSION,
    }
    digest_hex = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return RailPathCandidate(
        candidate_id=f"rail_cand_{digest_hex[:20]}",
        digest=f"sha256:{digest_hex}",
        rail_dataset_version_id=dataset.id,
        graph_version=dataset.graph_version,
        profile_version=dataset.profile_version,
        scoring_version=RAIL_SCORING_VERSION,
        routing_profile=route.profile,
        distance_m=route.distance_m,
        duration_ms=route.duration_ms,
        station_ids=tuple(station_ids),
        coordinates=route.coordinates,
        way_ranges=route.way_ranges,
        score=score,
        score_details=tuple(score_details),
        warnings=tuple(warnings),
        can_commit=score >= 0.70,
    )


def resolve_rail_path(
    db: Session,
    *,
    travel_date: date,
    train_no: str | None,
    train_type: RailTrainType,
    start_station_id: int,
    end_station_id: int,
    via_station_ids: list[int] | None = None,
    route_hint: str | None = None,
) -> RailPathResolution:
    settings = get_settings()
    dataset = ready_rail_dataset(db)
    _verify_sidecar_identity(dataset)
    station_ids = [
        start_station_id,
        *(via_station_ids or []),
        end_station_id,
    ]
    stations = _ordered_stations(db, dataset.id, station_ids)
    points = tuple((station.lat, station.lon) for station in stations)
    unique_by_geometry: dict[str, RailPathCandidate] = {}
    for profile_rank, profile in enumerate(_profiles(train_type)):
        try:
            route = fetch_sidecar_route(
                settings.rail_sidecar_url,
                settings.rail_sidecar_timeout_seconds,
                points=points,
                profile=profile,
            )
        except RailSidecarError as error:
            if error.code == "rail_no_path":
                continue
            raise RailResolutionError(error.code, str(error), 503) from error
        candidate = _candidate(
            dataset=dataset,
            travel_date=travel_date,
            train_no=train_no,
            train_type=train_type,
            route_hint=route_hint,
            station_ids=station_ids,
            station_coordinates=tuple(
                (station.lon, station.lat) for station in stations
            ),
            profile_rank=profile_rank,
            route=route,
        )
        geometry_hash = hashlib.sha256(
            json.dumps(candidate.coordinates, separators=(",", ":")).encode()
        ).hexdigest()
        unique_by_geometry.setdefault(geometry_hash, candidate)
    candidates = tuple(
        sorted(
            unique_by_geometry.values(),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
    )[:3]
    if not candidates:
        return RailPathResolution(status="unresolved", candidates=())
    if (
        len(candidates) == 1
        and candidates[0].score >= 0.90
        and not candidates[0].warnings
    ):
        return RailPathResolution(status="resolved", candidates=candidates)
    return RailPathResolution(status="needs_review", candidates=candidates)
