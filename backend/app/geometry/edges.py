from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from statistics import median
from typing import TypeAlias

from pyproj import CRS, Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring, transform

LineGeometry: TypeAlias = LineString | MultiLineString


class GeometryBuildError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SourceStop:
    station_id: int
    sequence: int
    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class ProjectedStop:
    station_id: int
    sequence: int
    measure_m: float
    projection_error_m: float


@dataclass(frozen=True, slots=True)
class BuiltEdge:
    from_station_id: int
    to_station_id: int
    sequence_from: int
    sequence_to: int
    distance_m: float
    geometry: LineString
    bbox: tuple[float, float, float, float]
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BuiltRoute:
    oriented_geometry: LineString
    projected_stops: tuple[ProjectedStop, ...]
    edges: tuple[BuiltEdge, ...]
    was_reversed: bool


def _validate_wgs84(geometry: BaseGeometry, stops: list[SourceStop]) -> None:
    min_lon, min_lat, max_lon, max_lat = geometry.bounds
    if min_lon < -180 or max_lon > 180 or min_lat < -90 or max_lat > 90:
        raise GeometryBuildError(
            "coordinate_out_of_range", "线路坐标不在 WGS-84 范围内"
        )
    for stop in stops:
        if not -180 <= stop.lon <= 180 or not -90 <= stop.lat <= 90:
            raise GeometryBuildError(
                "coordinate_out_of_range", f"站点 {stop.station_id} 坐标越界"
            )


def _as_connected_line(geometry: LineGeometry) -> LineString:
    if geometry.is_empty:
        raise GeometryBuildError("empty_geometry", "线路几何为空")
    if isinstance(geometry, LineString):
        line = geometry
    else:
        merged = linemerge(geometry)
        if not isinstance(merged, LineString):
            raise GeometryBuildError("disconnected_geometry", "线路几何包含不连续区段")
        line = merged
    if len(line.coords) < 2 or line.length <= 0:
        raise GeometryBuildError("invalid_geometry", "线路至少需要两个不同坐标点")
    return line


def _local_transformers(line: LineString) -> tuple[Transformer, Transformer]:
    center = line.centroid
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center.y:.12f} +lon_0={center.x:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    to_metric = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    return to_metric, to_wgs84


def reverse_line(geometry: LineGeometry) -> LineGeometry:
    """Reverse both coordinate order and part order without changing coordinates."""

    if isinstance(geometry, LineString):
        return LineString(list(geometry.coords)[::-1])
    return MultiLineString(
        [list(part.coords)[::-1] for part in reversed(list(geometry.geoms))]
    )


def build_route_edges(
    geometry: LineGeometry,
    source_stops: list[SourceStop],
    *,
    max_projection_error_m: float = 250,
    warning_projection_error_m: float = 80,
    monotonic_tolerance_m: float = 3,
) -> BuiltRoute:
    """Cut a non-loop WGS-84 route into route-aware adjacent station edges."""

    if len(source_stops) < 2:
        raise GeometryBuildError("too_few_stops", "线路至少需要两个站点")
    stops = sorted(source_stops, key=lambda stop: stop.sequence)
    if len({stop.sequence for stop in stops}) != len(stops):
        raise GeometryBuildError("duplicate_sequence", "站点 sequence 必须唯一")

    line = _as_connected_line(geometry)
    _validate_wgs84(line, stops)
    if line.is_ring:
        raise GeometryBuildError(
            "loop_requires_variant", "环线必须使用有方向的环形构建器"
        )

    to_metric, to_wgs84 = _local_transformers(line)

    def project(current_line: LineString) -> tuple[LineString, list[float]]:
        metric = transform(to_metric.transform, current_line)
        if not isinstance(metric, LineString):
            raise GeometryBuildError("projection_failed", "线路投影结果类型错误")
        measures = [
            metric.project(transform(to_metric.transform, Point(stop.lon, stop.lat)))
            for stop in stops
        ]
        return metric, measures

    metric_line, measures = project(line)
    meaningful_deltas = [
        current - previous
        for previous, current in pairwise(measures)
        if abs(current - previous) > monotonic_tolerance_m
    ]
    if not meaningful_deltas:
        raise GeometryBuildError("collapsed_stops", "站点无法沿线路形成有效顺序")

    was_reversed = median(meaningful_deltas) < 0
    if was_reversed:
        reversed_line = reverse_line(line)
        if not isinstance(reversed_line, LineString):
            raise GeometryBuildError("invalid_geometry", "线路反转失败")
        line = reversed_line
        metric_line, measures = project(line)

    for previous, current in pairwise(measures):
        if current <= previous + monotonic_tolerance_m:
            raise GeometryBuildError("non_monotonic_stops", "站点顺序与线路走向不单调")

    projected_stops: list[ProjectedStop] = []
    for stop, measure in zip(stops, measures, strict=True):
        metric_point = transform(to_metric.transform, Point(stop.lon, stop.lat))
        error_m = metric_point.distance(metric_line.interpolate(measure))
        if error_m > max_projection_error_m:
            raise GeometryBuildError(
                "projection_error_too_large",
                f"站点 {stop.station_id} 偏离线路 {error_m:.1f} 米",
            )
        projected_stops.append(
            ProjectedStop(
                station_id=stop.station_id,
                sequence=stop.sequence,
                measure_m=measure,
                projection_error_m=error_m,
            )
        )

    edges: list[BuiltEdge] = []
    for start, end in pairwise(projected_stops):
        metric_edge = substring(metric_line, start.measure_m, end.measure_m)
        if not isinstance(metric_edge, LineString) or metric_edge.length <= 0.1:
            raise GeometryBuildError("empty_edge", "相邻站点生成了空区间")
        wgs84_edge = transform(to_wgs84.transform, metric_edge)
        if not isinstance(wgs84_edge, LineString):
            raise GeometryBuildError("projection_failed", "区间反投影结果类型错误")
        flags = tuple(
            [
                "projection_error_warning"
                for projected in (start, end)
                if projected.projection_error_m > warning_projection_error_m
            ]
        )
        edges.append(
            BuiltEdge(
                from_station_id=start.station_id,
                to_station_id=end.station_id,
                sequence_from=start.sequence,
                sequence_to=end.sequence,
                distance_m=metric_edge.length,
                geometry=wgs84_edge,
                bbox=wgs84_edge.bounds,
                quality_flags=flags,
            )
        )

    return BuiltRoute(
        oriented_geometry=line,
        projected_stops=tuple(projected_stops),
        edges=tuple(edges),
        was_reversed=was_reversed,
    )


def build_loop_edges(
    geometry: LineGeometry,
    source_stops: list[SourceStop],
    *,
    max_projection_error_m: float = 250,
    warning_projection_error_m: float = 80,
) -> BuiltRoute:
    """Cut a loop into a complete directed edge ring in source stop order."""

    if len(source_stops) < 3:
        raise GeometryBuildError("too_few_stops", "环线至少需要三个站点")
    stops = sorted(source_stops, key=lambda stop: stop.sequence)
    if len({stop.sequence for stop in stops}) != len(stops):
        raise GeometryBuildError("duplicate_sequence", "站点 sequence 必须唯一")

    line = _as_connected_line(geometry)
    _validate_wgs84(line, stops)
    if not line.is_ring:
        to_metric, _ = _local_transformers(line)
        metric = transform(to_metric.transform, line)
        if not isinstance(metric, LineString):
            raise GeometryBuildError("projection_failed", "环线投影失败")
        if Point(metric.coords[0]).distance(Point(metric.coords[-1])) > 500:
            raise GeometryBuildError("open_loop", "标记为环线的几何首尾未闭合")
        line = LineString([*line.coords, line.coords[0]])

    to_metric, to_wgs84 = _local_transformers(line)

    def project(current_line: LineString) -> tuple[LineString, list[float]]:
        metric_line = transform(to_metric.transform, current_line)
        if not isinstance(metric_line, LineString):
            raise GeometryBuildError("projection_failed", "环线投影结果类型错误")
        measures = [
            metric_line.project(
                transform(to_metric.transform, Point(stop.lon, stop.lat))
            )
            for stop in stops
        ]
        return metric_line, measures

    metric_line, measures = project(line)
    length_m = metric_line.length
    forward_score = sum(
        (current - previous) % length_m for previous, current in pairwise(measures)
    )
    reverse_score = sum(
        (previous - current) % length_m for previous, current in pairwise(measures)
    )
    was_reversed = reverse_score < forward_score
    if was_reversed:
        reversed_line = reverse_line(line)
        if not isinstance(reversed_line, LineString):
            raise GeometryBuildError("invalid_geometry", "环线反转失败")
        line = reversed_line
        metric_line, measures = project(line)
        length_m = metric_line.length

    projected_stops: list[ProjectedStop] = []
    for stop, measure in zip(stops, measures, strict=True):
        metric_point = transform(to_metric.transform, Point(stop.lon, stop.lat))
        error_m = metric_point.distance(metric_line.interpolate(measure))
        if error_m > max_projection_error_m:
            raise GeometryBuildError(
                "projection_error_too_large",
                f"站点 {stop.station_id} 偏离环线 {error_m:.1f} 米",
            )
        projected_stops.append(
            ProjectedStop(
                station_id=stop.station_id,
                sequence=stop.sequence,
                measure_m=measure,
                projection_error_m=error_m,
            )
        )

    edges: list[BuiltEdge] = []
    stop_pairs = list(pairwise(projected_stops))
    stop_pairs.append((projected_stops[-1], projected_stops[0]))
    for start, end in stop_pairs:
        if end.measure_m > start.measure_m:
            metric_edge = substring(metric_line, start.measure_m, end.measure_m)
        else:
            tail = substring(metric_line, start.measure_m, length_m)
            head = substring(metric_line, 0, end.measure_m)
            parts = [
                part
                for part in (tail, head)
                if isinstance(part, LineString) and part.length > 0.1
            ]
            if not parts:
                raise GeometryBuildError("disconnected_edge", "环线跨零点区间为空")
            if len(parts) == 1:
                metric_edge = parts[0]
            else:
                merged = linemerge(parts)
                if not isinstance(merged, LineString):
                    raise GeometryBuildError(
                        "disconnected_edge", "环线跨零点区间不连续"
                    )
                metric_edge = merged
        if not isinstance(metric_edge, LineString) or metric_edge.length <= 0.1:
            raise GeometryBuildError("empty_edge", "环线相邻站点生成了空区间")
        wgs84_edge = transform(to_wgs84.transform, metric_edge)
        if not isinstance(wgs84_edge, LineString):
            raise GeometryBuildError("projection_failed", "环线区间反投影失败")
        flags = tuple(
            "projection_error_warning"
            for projected in (start, end)
            if projected.projection_error_m > warning_projection_error_m
        )
        edges.append(
            BuiltEdge(
                from_station_id=start.station_id,
                to_station_id=end.station_id,
                sequence_from=start.sequence,
                sequence_to=end.sequence,
                distance_m=metric_edge.length,
                geometry=wgs84_edge,
                bbox=wgs84_edge.bounds,
                quality_flags=flags,
            )
        )

    return BuiltRoute(
        oriented_geometry=line,
        projected_stops=tuple(projected_stops),
        edges=tuple(edges),
        was_reversed=was_reversed,
    )
