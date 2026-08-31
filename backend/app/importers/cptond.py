from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString, Point
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    City,
    DatasetVersion,
    Line,
    RouteEdge,
    RouteStop,
    RouteVariant,
    Station,
)
from app.db.session import SessionLocal
from app.geometry.edges import (
    GeometryBuildError,
    SourceStop,
    build_loop_edges,
    build_route_edges,
)
from app.matching.names import (
    normalize_city_name,
    normalize_line_name,
    normalize_station_name,
    pinyin_keys,
)

CPTOND_SOURCE_URL = "https://doi.org/10.6084/m9.figshare.29377427"
CPTOND_LICENSE = "CC BY 4.0"
SCIENCEDB_TIMELINE_SOURCE_URL = "https://doi.org/10.57760/sciencedb.33335"
SCIENCEDB_TIMELINE_LICENSE = "CC BY-NC-SA 4.0"
SCIENCEDB_TIMELINE_CAPTURED_AT = "2025-06（时序补充至 2025）"
IMPORTER_SCHEMA_VERSION = "cptond-v2.3"
OFFICIAL_FORMAT = "cptond-v2"
TIMELINE_FORMAT = "sciencedb-timeline-v1"
_GEOD = Geod(ellps="WGS84")
logger = logging.getLogger(__name__)


class DatasetAuditError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DatasetBundle:
    routes_path: Path
    stops_path: Path
    segments_path: Path | None = None
    source_format: str = OFFICIAL_FORMAT


@dataclass(frozen=True, slots=True)
class DatasetAudit:
    root: Path
    bundles: tuple[DatasetBundle, ...]
    checksum: str
    route_count: int
    stop_count: int
    source_format: str
    source_url: str
    license: str
    captured_at: str
    default_source_version: str


@dataclass(frozen=True, slots=True)
class DatasetImportHandle:
    import_id: int
    status: str
    should_run: bool


ROUTE_FIELDS = {
    "route_id": ("route_id",),
    "route_cn": ("route_cn", "name_cn", "route", "name"),
    "route_en": ("route_en", "name_en", "route_en_name"),
    "city_code": ("city_code",),
    "city_cn": ("city_cn", "city"),
    "city_en": ("city_en",),
    "loop": ("loop", "is_loop"),
    "start_stop": ("start_stop",),
    "end_stop": ("end_stop",),
}
STOP_FIELDS = {
    "stop_id": ("stop_id",),
    "name_cn": ("name_cn", "stop_cn", "name", "stop_name"),
    "name_en": ("name_en", "stop_en"),
    "route_id": ("route_id",),
    "route_cn": ("route_cn", "route"),
    "city_code": ("city_code",),
    "city_cn": ("city_cn", "city"),
    "city_en": ("city_en",),
    "sequence": ("sequence",),
}
SEGMENT_FIELDS = {
    "route_id": ("route_id", "s_route_id", "e_route_id"),
    "route_cn": ("route_cn", "route"),
    "city_code": ("city_code",),
    "city_cn": ("city_cn", "city"),
    "city_en": ("city_en",),
    "sequence": ("seg_seq", "sequence"),
    "start_stop_id": ("s_stop_id", "s_stopid"),
    "end_stop_id": ("e_stop_id", "e_stopid"),
    "start_name": ("s_name", "s_name_cn", "s_stop_cn", "start_name"),
    "end_name": ("e_name", "e_name_cn", "e_stop_cn", "end_name"),
}


def _sidecars(path: Path) -> list[Path]:
    required = [path.with_suffix(suffix) for suffix in (".shp", ".shx", ".dbf", ".prj")]
    missing = [candidate.name for candidate in required if not candidate.is_file()]
    if missing:
        raise DatasetAuditError(
            "missing_shapefile_sidecar",
            f"{path.name} 缺少必要文件：{', '.join(missing)}",
        )
    optional = [path.with_suffix(suffix) for suffix in (".cpg", ".qix")]
    return [*required, *(candidate for candidate in optional if candidate.is_file())]


def discover_bundles(root: Path) -> tuple[DatasetBundle, ...]:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise DatasetAuditError("data_directory_not_found", "CPTOND 数据目录不存在")

    national_routes = sorted(resolved.rglob("metro_routes.shp"))
    for routes_path in national_routes:
        stops_path = routes_path.with_name("metro_stops.shp")
        if stops_path.is_file():
            return (DatasetBundle(routes_path=routes_path, stops_path=stops_path),)

    bundles: list[DatasetBundle] = []
    for routes_path in sorted(resolved.rglob("*_metro_routes.shp")):
        stops_path = routes_path.with_name(
            routes_path.name.replace("_metro_routes.shp", "_metro_stops.shp")
        )
        if stops_path.is_file():
            bundles.append(
                DatasetBundle(routes_path=routes_path, stops_path=stops_path)
            )
    if bundles:
        return tuple(bundles)

    timeline_bundles: list[DatasetBundle] = []
    for routes_path in national_routes:
        segments_path = routes_path.with_name("metro_routes_segment_timeline.shp")
        station_candidates = (
            routes_path.with_name("metro_stations_timeline.shp"),
            routes_path.with_name("metro_stops_timeline.shp"),
        )
        timeline_stops_path = next(
            (candidate for candidate in station_candidates if candidate.is_file()),
            None,
        )
        if segments_path.is_file() and timeline_stops_path is not None:
            timeline_bundles.append(
                DatasetBundle(
                    routes_path=routes_path,
                    stops_path=timeline_stops_path,
                    segments_path=segments_path,
                    source_format=TIMELINE_FORMAT,
                )
            )
    if timeline_bundles:
        return tuple(timeline_bundles)

    raise DatasetAuditError(
        "metro_files_not_found",
        "未找到 CPTOND 线路/站点文件对，或 Science Data Bank 的线路/分段/站点三文件",
    )


def _field_map(
    columns: list[str], aliases: dict[str, tuple[str, ...]]
) -> dict[str, str]:
    lower_to_actual = {column.casefold(): column for column in columns}
    result: dict[str, str] = {}
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            if candidate in lower_to_actual:
                result[canonical] = lower_to_actual[candidate]
                break
    return result


def _validate_schema(
    frame: gpd.GeoDataFrame,
    *,
    aliases: dict[str, tuple[str, ...]],
    required: set[str],
    label: str,
) -> None:
    fields = _field_map(list(frame.columns), aliases)
    missing = sorted(required - fields.keys())
    if missing:
        raise DatasetAuditError(
            "unsupported_schema",
            f"{label} 缺少字段：{', '.join(missing)}",
        )
    if frame.crs is None:
        raise DatasetAuditError("missing_crs", f"{label} 缺少 CRS")


def audit_dataset(root: Path) -> DatasetAudit:
    bundles = discover_bundles(root)
    digest = hashlib.sha256()
    route_count = 0
    stop_count = 0
    seen_files: set[Path] = set()

    for bundle in bundles:
        routes = gpd.read_file(bundle.routes_path, rows=1)
        stops = gpd.read_file(bundle.stops_path, rows=1)
        _validate_schema(
            routes,
            aliases=ROUTE_FIELDS,
            required=(
                {"route_cn", "city_cn"}
                if bundle.source_format == TIMELINE_FORMAT
                else {"route_id", "route_cn", "city_cn"}
            ),
            label=bundle.routes_path.name,
        )
        _validate_schema(
            stops,
            aliases=STOP_FIELDS,
            required=(
                {"stop_id", "name_cn", "route_id", "city_cn"}
                if bundle.source_format == TIMELINE_FORMAT
                else {"stop_id", "name_cn", "route_id", "sequence", "city_cn"}
            ),
            label=bundle.stops_path.name,
        )
        if bundle.segments_path is not None:
            segments = gpd.read_file(bundle.segments_path, rows=1)
            _validate_schema(
                segments,
                aliases=SEGMENT_FIELDS,
                required={
                    "route_id",
                    "sequence",
                    "start_stop_id",
                    "end_stop_id",
                    "start_name",
                    "end_name",
                    "city_cn",
                },
                label=bundle.segments_path.name,
            )
        route_count += len(gpd.read_file(bundle.routes_path, ignore_geometry=True))
        stop_count += len(gpd.read_file(bundle.stops_path, ignore_geometry=True))
        shape_paths = [bundle.routes_path, bundle.stops_path]
        if bundle.segments_path is not None:
            shape_paths.append(bundle.segments_path)
        for shape_path in shape_paths:
            for file_path in _sidecars(shape_path):
                if file_path in seen_files:
                    continue
                seen_files.add(file_path)
                digest.update(file_path.name.encode())
                with file_path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)

    source_formats = {bundle.source_format for bundle in bundles}
    if len(source_formats) != 1:
        raise DatasetAuditError(
            "mixed_source_formats",
            "同一次导入不能混用 CPTOND 原包和 Science Data Bank 时序数据",
        )
    source_format = source_formats.pop()
    is_timeline = source_format == TIMELINE_FORMAT
    return DatasetAudit(
        root=root.expanduser().resolve(),
        bundles=bundles,
        checksum=digest.hexdigest(),
        route_count=route_count,
        stop_count=stop_count,
        source_format=source_format,
        source_url=(
            SCIENCEDB_TIMELINE_SOURCE_URL if is_timeline else CPTOND_SOURCE_URL
        ),
        license=SCIENCEDB_TIMELINE_LICENSE if is_timeline else CPTOND_LICENSE,
        captured_at=SCIENCEDB_TIMELINE_CAPTURED_AT if is_timeline else "2025-06",
        default_source_version="timeline-v1" if is_timeline else "v2",
    )


def _text(value: Any, default: str = "") -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    return str(value).strip()


def _identifier(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _text(value)


def _is_loop(value: Any, geometry: LineString | MultiLineString) -> bool:
    normalized = _text(value).casefold()
    if normalized in {"1", "true", "yes", "是", "环线", "loop"}:
        return True
    return isinstance(geometry, LineString) and geometry.is_ring


def _line_endpoint(geometry: LineString | MultiLineString, *, start: bool) -> Point:
    if isinstance(geometry, LineString):
        coordinate = geometry.coords[0 if start else -1]
    else:
        parts = list(geometry.geoms)
        part = parts[0 if start else -1]
        coordinate = part.coords[0 if start else -1]
    return Point(float(coordinate[0]), float(coordinate[1]))


def _same_timeline_stop(
    left_id: str, left_name: str, right_id: str, right_name: str
) -> bool:
    if left_id and right_id:
        return left_id == right_id
    return normalize_station_name(left_name) == normalize_station_name(right_name)


def _timeline_stops(
    routes: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    route_fields = _field_map(list(routes.columns), ROUTE_FIELDS)
    station_fields = _field_map(list(stations.columns), STOP_FIELDS)
    segment_fields = _field_map(list(segments.columns), SEGMENT_FIELDS)

    exact_stations: dict[tuple[str, str, str], list[pd.Series[Any]]] = {}
    city_stations: dict[tuple[str, str], list[pd.Series[Any]]] = {}
    named_stations: dict[tuple[str, str], list[pd.Series[Any]]] = {}
    for _, station in stations.iterrows():
        city_key = _city_key(station, station_fields)
        route_id = _identifier(station[station_fields["route_id"]])
        stop_id = _identifier(station[station_fields["stop_id"]])
        name = _text(station[station_fields["name_cn"]])
        exact_stations.setdefault((city_key, route_id, stop_id), []).append(station)
        city_stations.setdefault((city_key, stop_id), []).append(station)
        named_stations.setdefault((city_key, normalize_station_name(name)), []).append(
            station
        )

    segment_route_ids = segments[segment_fields["route_id"]].map(_identifier)
    segment_city_keys = segments.apply(
        lambda row: _city_key(row, segment_fields), axis=1
    )
    route_ids_by_name: dict[tuple[str, str], set[str]] = {}
    for segment_position, (_, segment) in enumerate(segments.iterrows()):
        route_key = (
            _text(segment_city_keys.iloc[segment_position]),
            normalize_line_name(_text(segment[segment_fields["route_cn"]])),
        )
        route_ids_by_name.setdefault(route_key, set()).add(
            _identifier(segment[segment_fields["route_id"]])
        )
    canonical_records: list[dict[str, Any]] = []
    routes = routes.copy()
    if "route_id" not in route_fields:
        routes["route_id"] = None
        route_fields["route_id"] = "route_id"
    if "start_stop" not in routes.columns:
        routes["start_stop"] = None
    if "end_stop" not in routes.columns:
        routes["end_stop"] = None

    for route_index, route in routes.iterrows():
        route_id = _identifier(route[route_fields["route_id"]])
        city_key = _city_key(route, route_fields)
        if not route_id:
            route_name = normalize_line_name(_text(route[route_fields["route_cn"]]))
            candidate_ids = route_ids_by_name.get((city_key, route_name), set())
            if len(candidate_ids) != 1:
                logger.warning(
                    "Science Data Bank route %s/%s resolves to %d route IDs",
                    city_key,
                    route_name,
                    len(candidate_ids),
                )
                continue
            route_id = next(iter(candidate_ids))
            routes.at[route_index, route_fields["route_id"]] = route_id
        route_segments = segments[
            (segment_route_ids == route_id) & (segment_city_keys == city_key)
        ].copy()
        route_segments["_timeline_sequence"] = pd.to_numeric(
            route_segments[segment_fields["sequence"]], errors="coerce"
        )
        route_segments = route_segments.dropna(
            subset=["_timeline_sequence"]
        ).sort_values("_timeline_sequence")
        if route_segments.empty:
            logger.warning(
                "Science Data Bank route %s/%s has no ordered segments",
                city_key,
                route_id,
            )
            continue

        endpoints: list[tuple[str, str, Point]] = []
        continuous = True
        for _, segment in route_segments.iterrows():
            geometry = segment.geometry
            if not isinstance(geometry, (LineString, MultiLineString)):
                continuous = False
                break
            start_id = _identifier(segment[segment_fields["start_stop_id"]])
            end_id = _identifier(segment[segment_fields["end_stop_id"]])
            start_name = _text(segment[segment_fields["start_name"]])
            end_name = _text(segment[segment_fields["end_name"]])
            if _same_timeline_stop(start_id, start_name, end_id, end_name):
                # The real timeline dataset uses zero-length self segments as
                # direction anchors on several circular routes. They carry no
                # traversable edge and would otherwise duplicate a RouteStop.
                continue
            start_point = _line_endpoint(geometry, start=True)
            end_point = _line_endpoint(geometry, start=False)
            if not endpoints:
                endpoints.append((start_id, start_name, start_point))
            elif not _same_timeline_stop(
                endpoints[-1][0], endpoints[-1][1], start_id, start_name
            ):
                continuous = False
                break
            endpoints.append((end_id, end_name, end_point))
        if not continuous or len(endpoints) < 2:
            logger.warning(
                "Science Data Bank route %s/%s has disconnected segments",
                city_key,
                route_id,
            )
            continue

        route_name = _text(route[route_fields["route_cn"]])
        route_city_cn = _text(route[route_fields["city_cn"]])
        route_city_code = (
            _text(route[route_fields["city_code"]])
            if "city_code" in route_fields
            else ""
        )
        route_city_en = (
            _text(route[route_fields["city_en"]]) if "city_en" in route_fields else ""
        )
        routes.at[route_index, "start_stop"] = endpoints[0][1]
        routes.at[route_index, "end_stop"] = endpoints[-1][1]

        for sequence, (stop_id, segment_name, fallback_point) in enumerate(
            endpoints, start=1
        ):
            candidates = exact_stations.get((city_key, route_id, stop_id), [])
            if not candidates:
                candidates = city_stations.get((city_key, stop_id), [])
            if not candidates:
                candidates = named_stations.get(
                    (city_key, normalize_station_name(segment_name)), []
                )
            station_row = candidates[0] if candidates else None
            point = station_row.geometry if station_row is not None else fallback_point
            if not isinstance(point, Point):
                point = fallback_point
            station_name = (
                _text(station_row[station_fields["name_cn"]])
                if station_row is not None
                else ""
            )
            name_en_field = station_fields.get("name_en")
            name_en = (
                _text(station_row[name_en_field])
                if station_row is not None and name_en_field is not None
                else ""
            )
            canonical_records.append(
                {
                    "stop_id": stop_id or f"{route_id}:{sequence}",
                    "name_cn": station_name or segment_name,
                    "name_en": name_en,
                    "route_id": route_id,
                    "route_cn": route_name,
                    "city_code": route_city_code,
                    "city_cn": route_city_cn,
                    "city_en": route_city_en,
                    "sequence": sequence,
                    "geometry": point,
                }
            )

    if not canonical_records:
        raise DatasetAuditError(
            "timeline_stop_reconstruction_failed",
            "Science Data Bank 分段数据未能重建任何线路站序",
        )
    return routes, gpd.GeoDataFrame(
        canonical_records, geometry="geometry", crs="EPSG:4326"
    )


def _read_all(audit: DatasetAudit) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    route_frames: list[gpd.GeoDataFrame] = []
    stop_frames: list[gpd.GeoDataFrame] = []
    for bundle in audit.bundles:
        routes = gpd.read_file(bundle.routes_path)
        stops = gpd.read_file(bundle.stops_path)
        frames = [routes, stops]
        segments = None
        if bundle.segments_path is not None:
            segments = gpd.read_file(bundle.segments_path)
            frames.append(segments)
        if any(frame.crs is None for frame in frames):
            raise DatasetAuditError("missing_crs", "线路、分段或站点文件缺少 CRS")
        routes = routes.to_crs("EPSG:4326")
        stops = stops.to_crs("EPSG:4326")
        if segments is not None:
            routes, stops = _timeline_stops(routes, stops, segments.to_crs("EPSG:4326"))
        route_frames.append(routes)
        stop_frames.append(stops)
    if any(frame.crs is None for frame in [*route_frames, *stop_frames]):
        raise DatasetAuditError("missing_crs", "线路或站点文件缺少 CRS")
    routes = gpd.GeoDataFrame(
        pd.concat(route_frames, ignore_index=True), crs="EPSG:4326"
    )
    stops = gpd.GeoDataFrame(pd.concat(stop_frames, ignore_index=True), crs="EPSG:4326")
    return routes, stops


def _canonical_station(
    db: Session,
    *,
    city: City,
    row: pd.Series[Any],
    fields: dict[str, str],
    cache: dict[str, list[Station]],
) -> Station:
    geometry = row.geometry
    if not isinstance(geometry, Point):
        raise DatasetAuditError("invalid_stop_geometry", "站点几何必须是 Point")
    name_cn = _text(row[fields["name_cn"]])
    normalized = normalize_station_name(name_cn)
    if not normalized:
        raise DatasetAuditError("empty_station_name", "站点中文名不能为空")
    candidates = cache.setdefault(normalized, [])
    for candidate in candidates:
        _, _, distance_m = _GEOD.inv(
            candidate.lon, candidate.lat, geometry.x, geometry.y
        )
        if distance_m <= 500:
            return candidate
    name_en_field = fields.get("name_en")
    name_en = _text(row[name_en_field]) if name_en_field else None
    pinyin_full, pinyin_initials = pinyin_keys(name_cn)
    station = Station(
        city_id=city.id,
        name_cn=name_cn,
        name_en=name_en or None,
        normalized_name=normalized,
        pinyin_full=pinyin_full,
        pinyin_initials=pinyin_initials,
        lon=geometry.x,
        lat=geometry.y,
        cluster_no=len(candidates),
    )
    db.add(station)
    db.flush()
    candidates.append(station)
    return station


def _city_key(row: pd.Series[Any], fields: dict[str, str]) -> str:
    city_code = _text(row[fields["city_code"]]) if "city_code" in fields else ""
    city_cn = _text(row[fields["city_cn"]])
    return city_code or normalize_city_name(city_cn)


def _import_into_session(
    db: Session, dataset: DatasetVersion, audit: DatasetAudit
) -> None:
    routes, stops = _read_all(audit)
    route_fields = _field_map(list(routes.columns), ROUTE_FIELDS)
    stop_fields = _field_map(list(stops.columns), STOP_FIELDS)
    route_city_keys = routes.apply(lambda row: _city_key(row, route_fields), axis=1)
    stop_city_keys = stops.apply(lambda row: _city_key(row, stop_fields), axis=1)
    city_keys = sorted(set(route_city_keys) & set(stop_city_keys))
    dataset.status = "checking"
    dataset.total_cities = len(city_keys)
    dataset.processed_cities = 0
    dataset.ready_lines = 0
    dataset.blocked_lines = 0
    dataset.error_code = None
    dataset.error_message = None
    db.commit()

    ready_cities = 0
    for city_key in city_keys:
        db.refresh(dataset)
        if dataset.status == "cancelled":
            raise DatasetAuditError("import_cancelled", "数据导入已取消")
        city_routes = routes[route_city_keys == city_key]
        city_stops = stops[stop_city_keys == city_key]
        if city_routes.empty or city_stops.empty:
            continue
        bounds = city_routes.total_bounds
        first_route = city_routes.iloc[0]
        city_cn = _text(first_route[route_fields["city_cn"]])
        city_en_field = route_fields.get("city_en")
        city_en = _text(first_route[city_en_field]) if city_en_field else ""
        city = City(
            dataset_version_id=dataset.id,
            source_city_code=city_key,
            name_cn=city_cn,
            name_en=city_en or None,
            center_lon=float((bounds[0] + bounds[2]) / 2),
            center_lat=float((bounds[1] + bounds[3]) / 2),
            min_lon=float(bounds[0]),
            min_lat=float(bounds[1]),
            max_lon=float(bounds[2]),
            max_lat=float(bounds[3]),
            status="checking",
        )
        db.add(city)
        db.flush()
        line_cache: dict[str, Line] = {}
        station_cache: dict[str, list[Station]] = {}
        city_ready_lines = 0

        for route_index, route_row in city_routes.iterrows():
            geometry = route_row.geometry
            if not isinstance(geometry, (LineString, MultiLineString)):
                continue
            route_name = _text(route_row[route_fields["route_cn"]])
            normalized_line = normalize_line_name(route_name)
            if not normalized_line:
                continue
            line = line_cache.get(normalized_line)
            if line is None:
                route_en_field = route_fields.get("route_en")
                route_en = _text(route_row[route_en_field]) if route_en_field else ""
                line = Line(
                    city_id=city.id,
                    name_cn=route_name,
                    name_en=route_en or None,
                    normalized_name=normalized_line,
                    display_color=None,
                    sort_order=len(line_cache),
                    status="checking",
                )
                db.add(line)
                db.flush()
                line_cache[normalized_line] = line

            raw_route_id = _text(route_row[route_fields["route_id"]])
            route_mask = city_stops[stop_fields["route_id"]].astype(str) == raw_route_id
            route_stops = city_stops[route_mask].copy()
            if route_stops.empty and "route_cn" in stop_fields:
                route_stops = city_stops[
                    city_stops[stop_fields["route_cn"]].map(
                        lambda value, expected=normalized_line: (
                            normalize_line_name(_text(value)) == expected
                        )
                    )
                ].copy()
            route_stops["_sequence"] = pd.to_numeric(
                route_stops[stop_fields["sequence"]], errors="coerce"
            )
            route_stops = route_stops.dropna(subset=["_sequence"]).sort_values(
                "_sequence"
            )
            route_stops = route_stops.drop_duplicates(
                subset=["_sequence"], keep="first"
            )

            loop_field = route_fields.get("loop")
            loop_value = route_row[loop_field] if loop_field else None
            is_loop = _is_loop(loop_value, geometry)

            source_stops: list[SourceStop] = []
            stop_records: list[tuple[pd.Series[Any], Station]] = []
            for _, stop_row in route_stops.iterrows():
                station = _canonical_station(
                    db,
                    city=city,
                    row=stop_row,
                    fields=stop_fields,
                    cache=station_cache,
                )
                point = stop_row.geometry
                if not isinstance(point, Point):
                    continue
                sequence = int(stop_row["_sequence"])
                source_stops.append(
                    SourceStop(
                        station_id=station.id,
                        sequence=sequence,
                        lon=point.x,
                        lat=point.y,
                    )
                )
                stop_records.append((stop_row, station))

            if (
                is_loop
                and len(source_stops) >= 2
                and source_stops[0].station_id == source_stops[-1].station_id
            ):
                source_stops.pop()
                stop_records.pop()
            try:
                built = (
                    build_loop_edges(geometry, source_stops)
                    if is_loop
                    else build_route_edges(geometry, source_stops)
                )
                quality_status = "ready"
                quality_flags: list[dict[str, Any]] = []
            except GeometryBuildError as error:
                built = None
                quality_status = "blocked"
                quality_flags = [{"code": error.code, "message": str(error)}]

            source_route_id = f"{city_key}:{raw_route_id or route_index}"
            start_field = route_fields.get("start_stop")
            end_field = route_fields.get("end_stop")
            start_name = _text(route_row[start_field]) if start_field else ""
            end_name = _text(route_row[end_field]) if end_field else ""
            variant = RouteVariant(
                line_id=line.id,
                dataset_version_id=dataset.id,
                source_route_id=source_route_id,
                source_route_name=route_name,
                direction_name=(
                    f"{start_name} → {end_name}" if start_name and end_name else None
                ),
                is_loop=is_loop,
                is_branch=False,
                geometry_wkb=(built.oriented_geometry if built else geometry).wkb,
                match_method="route_id",
                quality_status=quality_status,
                quality_flags_json=quality_flags,
            )
            db.add(variant)
            db.flush()
            if built is None:
                continue

            route_stop_by_sequence: dict[int, RouteStop] = {}
            projected_by_sequence = {
                projected.sequence: projected for projected in built.projected_stops
            }
            for stop_row, station in stop_records:
                sequence = int(stop_row["_sequence"])
                projected = projected_by_sequence[sequence]
                point = stop_row.geometry
                if not isinstance(point, Point):
                    continue
                record = RouteStop(
                    route_variant_id=variant.id,
                    station_id=station.id,
                    source_stop_id=_text(stop_row[stop_fields["stop_id"]]),
                    source_sequence=sequence,
                    source_lon=point.x,
                    source_lat=point.y,
                    projected_measure_m=projected.measure_m,
                    projection_error_m=projected.projection_error_m,
                    match_quality="exact_route_id",
                )
                db.add(record)
                db.flush()
                route_stop_by_sequence[sequence] = record

            for edge in built.edges:
                start = route_stop_by_sequence[edge.sequence_from]
                end = route_stop_by_sequence[edge.sequence_to]
                db.add(
                    RouteEdge(
                        route_variant_id=variant.id,
                        from_route_stop_id=start.id,
                        to_route_stop_id=end.id,
                        from_station_id=edge.from_station_id,
                        to_station_id=edge.to_station_id,
                        sequence_from=edge.sequence_from,
                        sequence_to=edge.sequence_to,
                        distance_m=edge.distance_m,
                        geometry_wkb=edge.geometry.wkb,
                        min_lon=edge.bbox[0],
                        min_lat=edge.bbox[1],
                        max_lon=edge.bbox[2],
                        max_lat=edge.bbox[3],
                        quality_status="ready",
                        quality_flags_json=[
                            {"code": flag} for flag in edge.quality_flags
                        ],
                    )
                )
            line.status = "ready"

        for line in line_cache.values():
            variants = db.scalars(
                select(RouteVariant).where(RouteVariant.line_id == line.id)
            ).all()
            stop_sets = [
                frozenset(
                    db.scalars(
                        select(RouteStop.station_id).where(
                            RouteStop.route_variant_id == variant.id
                        )
                    ).all()
                )
                for variant in variants
                if variant.quality_status == "ready"
            ]
            has_branch = len(set(stop_sets)) > 1
            if has_branch:
                for variant in variants:
                    variant.is_branch = True
            if line.status == "checking":
                line.status = "blocked"

        city_ready_lines = sum(line.status == "ready" for line in line_cache.values())
        city.status = "ready" if city_ready_lines else "blocked"
        ready_cities += int(city.status == "ready")
        dataset.processed_cities += 1
        dataset.ready_lines += city_ready_lines
        dataset.blocked_lines += sum(
            line.status == "blocked" for line in line_cache.values()
        )
        db.commit()

    if ready_cities == 0:
        raise DatasetAuditError("no_ready_cities", "导入完成但没有城市通过质量门禁")
    db.execute(
        update(DatasetVersion)
        .where(
            DatasetVersion.id != dataset.id,
            DatasetVersion.source_name == dataset.source_name,
            DatasetVersion.status == "ready",
        )
        .values(status="retired")
    )
    dataset.status = "ready"
    dataset.completed_at = datetime.now(UTC)
    db.commit()


def clear_dataset_cities(db: Session, dataset_id: int) -> None:
    """Delete an unpublished dataset graph in foreign-key-safe order."""

    city_ids = select(City.id).where(City.dataset_version_id == dataset_id)
    variant_ids = select(RouteVariant.id).where(
        RouteVariant.dataset_version_id == dataset_id
    )
    db.execute(delete(RouteEdge).where(RouteEdge.route_variant_id.in_(variant_ids)))
    db.execute(delete(RouteStop).where(RouteStop.route_variant_id.in_(variant_ids)))
    db.execute(
        delete(RouteVariant).where(RouteVariant.dataset_version_id == dataset_id)
    )
    db.execute(delete(Line).where(Line.city_id.in_(city_ids)))
    db.execute(delete(Station).where(Station.city_id.in_(city_ids)))
    db.execute(delete(City).where(City.dataset_version_id == dataset_id))


def create_dataset_import(
    audit: DatasetAudit, source_version: str
) -> DatasetImportHandle:
    with SessionLocal() as db:
        existing = db.scalar(
            select(DatasetVersion).where(
                DatasetVersion.source_name == "CPTOND",
                DatasetVersion.source_version == source_version,
                DatasetVersion.checksum == audit.checksum,
            )
        )
        if existing is not None:
            if existing.status in {"failed", "cancelled"}:
                clear_dataset_cities(db, existing.id)
                existing.status = "staging"
                existing.completed_at = None
                existing.route_count = audit.route_count
                existing.stop_count = audit.stop_count
                existing.total_cities = 0
                existing.processed_cities = 0
                existing.ready_lines = 0
                existing.blocked_lines = 0
                existing.error_code = None
                existing.error_message = None
                db.commit()
                return DatasetImportHandle(existing.id, "staging", True)
            if existing.status == "retired":
                db.execute(
                    update(DatasetVersion)
                    .where(
                        DatasetVersion.id != existing.id,
                        DatasetVersion.source_name == existing.source_name,
                        DatasetVersion.status == "ready",
                    )
                    .values(status="retired")
                )
                existing.status = "ready"
                db.commit()
                return DatasetImportHandle(existing.id, "ready", False)
            return DatasetImportHandle(existing.id, existing.status, False)
        dataset = DatasetVersion(
            source_name="CPTOND",
            source_version=source_version,
            captured_at=audit.captured_at,
            license=audit.license,
            source_url=audit.source_url,
            checksum=audit.checksum,
            importer_schema_version=IMPORTER_SCHEMA_VERSION,
            route_count=audit.route_count,
            stop_count=audit.stop_count,
            status="staging",
        )
        db.add(dataset)
        db.commit()
        db.refresh(dataset)
        return DatasetImportHandle(dataset.id, dataset.status, True)


def run_dataset_import(dataset_id: int, audit: DatasetAudit) -> None:
    with SessionLocal() as db:
        dataset = db.get(DatasetVersion, dataset_id)
        if dataset is None or dataset.status in {"ready", "cancelled"}:
            return
        try:
            _import_into_session(db, dataset, audit)
        except Exception as error:
            db.rollback()
            dataset = db.get(DatasetVersion, dataset_id)
            was_cancelled = False
            if dataset is not None:
                was_cancelled = dataset.status == "cancelled"
                clear_dataset_cities(db, dataset_id)
                dataset.status = "cancelled" if was_cancelled else "failed"
                dataset.completed_at = datetime.now(UTC)
                dataset.error_code = (
                    "import_cancelled"
                    if was_cancelled
                    else getattr(error, "code", "unexpected_import_error")
                )
                dataset.error_message = str(error)[:2000]
                db.commit()
            if not was_cancelled:
                logger.exception("CPTOND import %s failed", dataset_id)
