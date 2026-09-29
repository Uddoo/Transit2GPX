from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

EXPECTED_RAIL_PROFILES = frozenset(
    {"china_high_speed", "china_emu", "china_conventional"}
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class RailSidecarError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RailSidecarInfo:
    version: str
    profiles: frozenset[str]
    bbox: tuple[float, float, float, float]
    import_date: str | None
    data_date: str | None
    graph_version: str
    pbf_sha256: str
    profile_version: str
    openrailrouting_commit: str


@dataclass(frozen=True, slots=True)
class RailWayRange:
    start_index: int
    end_index: int
    osm_way_id: int


@dataclass(frozen=True, slots=True)
class RailAttributeRange:
    attribute: str
    start_index: int
    end_index: int
    value: str | float | bool | None


@dataclass(frozen=True, slots=True)
class RailRoutePath:
    profile: str
    distance_m: float
    duration_ms: int
    coordinates: tuple[tuple[float, float], ...]
    way_ranges: tuple[RailWayRange, ...]
    attribute_ranges: tuple[RailAttributeRange, ...] = field(default_factory=tuple)


_SCORING_DETAIL_NAMES = (
    "max_speed",
    "rail_average_speed",
    "railway_class",
    "railway_service",
    "electrified",
)


def validate_loopback_url(base_url: str) -> str:
    parsed = urlsplit(base_url.rstrip("/"))
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RailSidecarError(
            "rail_sidecar_not_loopback",
            "铁路路径服务必须使用无凭据的 loopback HTTP 地址。",
        )
    return parsed.geturl().rstrip("/")


def fetch_sidecar_info(base_url: str, timeout_seconds: float) -> RailSidecarInfo:
    safe_base_url = validate_loopback_url(base_url)
    try:
        payload = _fetch_json(safe_base_url, "/info", timeout_seconds)
        identity = _fetch_sidecar_identity(safe_base_url, timeout_seconds)
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RailSidecarError(
            "rail_sidecar_unavailable",
            "铁路路径服务当前不可用。",
        ) from error
    if not isinstance(payload, dict):
        raise RailSidecarError(
            "rail_sidecar_invalid_response",
            "铁路路径服务返回了无法识别的状态。",
        )
    if not isinstance(identity, dict) or any(
        not isinstance(identity.get(field), str) or not identity[field]
        for field in (
            "graph_version",
            "pbf_sha256",
            "profile_version",
            "openrailrouting_commit",
        )
    ):
        raise RailSidecarError(
            "rail_sidecar_identity_missing",
            "铁路路径服务没有提供可验证的图版本身份。",
        )
    raw_profiles = payload.get("profiles")
    raw_bbox = payload.get("bbox")
    if not isinstance(raw_profiles, list) or not isinstance(raw_bbox, list):
        raise RailSidecarError(
            "rail_sidecar_invalid_response",
            "铁路路径服务状态缺少 Profile 或范围信息。",
        )
    profiles = frozenset(
        item["name"]
        for item in raw_profiles
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    )
    if len(raw_bbox) != 4 or not all(
        isinstance(value, int | float) for value in raw_bbox
    ):
        raise RailSidecarError(
            "rail_sidecar_invalid_response",
            "铁路路径服务返回了无效的图范围。",
        )
    return RailSidecarInfo(
        version=str(payload.get("version", "unknown")),
        profiles=profiles,
        bbox=tuple(float(value) for value in raw_bbox),  # type: ignore[arg-type]
        import_date=(
            str(payload["import_date"]) if payload.get("import_date") else None
        ),
        data_date=str(payload["data_date"]) if payload.get("data_date") else None,
        graph_version=identity["graph_version"],
        pbf_sha256=identity["pbf_sha256"],
        profile_version=identity["profile_version"],
        openrailrouting_commit=identity["openrailrouting_commit"],
    )


def _fetch_sidecar_identity(base_url: str, timeout_seconds: float) -> Any:
    try:
        return _fetch_json(base_url, "/transit2fog/metadata", timeout_seconds)
    except HTTPError as error:
        if error.code != 404:
            raise
        return _fetch_json(base_url, "/metro2fog/metadata", timeout_seconds)


def _fetch_json(base_url: str, path: str, timeout_seconds: float) -> Any:
    request = Request(
        f"{base_url}{path}",
        headers={"Accept": "application/json", "User-Agent": "Transit2GPX/rail-probe"},
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def fetch_sidecar_route(
    base_url: str,
    timeout_seconds: float,
    *,
    points: Sequence[tuple[float, float]],
    profile: str,
) -> RailRoutePath:
    if profile not in EXPECTED_RAIL_PROFILES:
        raise RailSidecarError("rail_profile_invalid", "铁路 Profile 不受支持。")
    if len(points) < 2:
        raise RailSidecarError("rail_points_invalid", "铁路路径至少需要两个站点。")
    parameters: list[tuple[str, str]] = []
    for latitude, longitude in points:
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise RailSidecarError(
                "rail_points_invalid", "铁路站点坐标超出 WGS-84 范围。"
            )
        parameters.append(("point", f"{latitude:.8f},{longitude:.8f}"))
    parameters.extend(
        [
            ("profile", profile),
            ("points_encoded", "false"),
            ("instructions", "false"),
            ("details", "osm_way_id"),
            *(("details", name) for name in _SCORING_DETAIL_NAMES),
        ]
    )
    safe_base_url = validate_loopback_url(base_url)
    request = Request(
        f"{safe_base_url}/route?{urlencode(parameters)}",
        headers={"Accept": "application/json", "User-Agent": "Transit2GPX/rail-route"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload: Any = json.load(response)
    except HTTPError as error:
        code = (
            "rail_no_path" if error.code in {400, 404} else "rail_sidecar_unavailable"
        )
        raise RailSidecarError(code, "铁路路径服务没有返回可用路径。") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RailSidecarError(
            "rail_sidecar_unavailable", "铁路路径服务当前不可用。"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("paths"), list):
        raise RailSidecarError(
            "rail_sidecar_invalid_response", "铁路路径服务返回了无法识别的路径。"
        )
    paths = payload["paths"]
    if not paths or not isinstance(paths[0], dict):
        raise RailSidecarError("rail_no_path", "没有找到经过指定站序的铁路路径。")
    path = paths[0]
    raw_points = path.get("points")
    raw_details = path.get("details")
    if not isinstance(raw_points, dict) or not isinstance(raw_details, dict):
        raise RailSidecarError(
            "rail_sidecar_invalid_response", "铁路路径缺少几何或来源引用。"
        )
    raw_coordinates = raw_points.get("coordinates")
    raw_way_ranges = raw_details.get("osm_way_id")
    if not isinstance(raw_coordinates, list) or not isinstance(raw_way_ranges, list):
        raise RailSidecarError(
            "rail_sidecar_invalid_response", "铁路路径几何或 OSM way 明细无效。"
        )
    coordinates: list[tuple[float, float]] = []
    for coordinate in raw_coordinates:
        if (
            not isinstance(coordinate, list)
            or len(coordinate) < 2
            or not all(isinstance(value, int | float) for value in coordinate[:2])
        ):
            raise RailSidecarError(
                "rail_sidecar_invalid_response", "铁路路径包含无效坐标。"
            )
        coordinates.append((float(coordinate[0]), float(coordinate[1])))
    way_ranges: list[RailWayRange] = []
    for item in raw_way_ranges:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not all(isinstance(value, int) for value in item)
        ):
            raise RailSidecarError(
                "rail_sidecar_invalid_response", "铁路路径包含无效 OSM way 引用。"
            )
        start_index, end_index, osm_way_id = item
        if start_index < 0 or end_index <= start_index or end_index >= len(coordinates):
            raise RailSidecarError(
                "rail_sidecar_invalid_response", "铁路路径 OSM way 范围越界。"
            )
        way_ranges.append(RailWayRange(start_index, end_index, osm_way_id))
    attribute_ranges: list[RailAttributeRange] = []
    for attribute in _SCORING_DETAIL_NAMES:
        raw_ranges = raw_details.get(attribute)
        if raw_ranges is None:
            continue
        if not isinstance(raw_ranges, list):
            raise RailSidecarError(
                "rail_sidecar_invalid_response",
                f"铁路路径包含无效 {attribute} 明细。",
            )
        for item in raw_ranges:
            if (
                not isinstance(item, list)
                or len(item) != 3
                or not isinstance(item[0], int)
                or not isinstance(item[1], int)
                or (
                    item[2] is not None
                    and not isinstance(item[2], str | int | float | bool)
                )
            ):
                raise RailSidecarError(
                    "rail_sidecar_invalid_response",
                    f"铁路路径包含无效 {attribute} 明细。",
                )
            start_index, end_index, value = item
            if (
                start_index < 0
                or end_index <= start_index
                or end_index >= len(coordinates)
            ):
                raise RailSidecarError(
                    "rail_sidecar_invalid_response",
                    f"铁路路径 {attribute} 范围越界。",
                )
            normalized_value = (
                float(value)
                if isinstance(value, int | float) and not isinstance(value, bool)
                else value
            )
            attribute_ranges.append(
                RailAttributeRange(
                    attribute=attribute,
                    start_index=start_index,
                    end_index=end_index,
                    value=normalized_value,
                )
            )
    distance = path.get("distance")
    duration = path.get("time")
    if (
        len(coordinates) < 2
        or not way_ranges
        or not isinstance(distance, int | float)
        or distance <= 0
        or not isinstance(duration, int)
    ):
        raise RailSidecarError(
            "rail_sidecar_invalid_response", "铁路路径长度、时间或几何无效。"
        )
    return RailRoutePath(
        profile=profile,
        distance_m=float(distance),
        duration_ms=duration,
        coordinates=tuple(coordinates),
        way_ranges=tuple(way_ranges),
        attribute_ranges=tuple(attribute_ranges),
    )
