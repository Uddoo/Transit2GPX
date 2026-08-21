from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Literal, cast

from lxml import etree
from pyproj import CRS, Geod, Transformer
from shapely import wkb
from shapely.geometry import LineString
from shapely.ops import transform
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Journey,
    JourneyLeg,
    JourneyLegEdge,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RouteEdge,
    RouteVariant,
)

GPX_NAMESPACE = "http://www.topografix.com/GPX/1/1"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
TRANSIT2FOG_RAIL_NAMESPACE = "https://transit2fog.local/gpx/rail/1"
_GEOD = Geod(ellps="WGS84")
_METRO_GPX_DESCRIPTION = (
    "Locally generated from CPTOND route edges; no synthetic time or elevation."
)


class ExportValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ExportOptions:
    mode: Literal["journeys", "coverage"]
    max_segment_length_m: int | None
    rail_max_segment_length_m: int | None = 200
    journey_ids: tuple[int, ...] = ()
    city_id: int | None = None
    line_id: int | None = None
    traveled_from: date | None = None
    traveled_to: date | None = None


@dataclass(frozen=True, slots=True)
class ExportEdge:
    edge_id: int
    coverage_key: str
    reversed: bool
    from_station_id: int | None
    to_station_id: int | None
    distance_m: float
    coordinates: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class ExportLeg:
    journey_id: int
    journey_code: str
    leg_no: int
    transport_mode: Literal["metro", "rail"]
    dataset_version_id: int
    graph_version: str | None
    profile_version: str | None
    candidate_digest: str
    source_geometry_sha256: str | None
    edges: tuple[ExportEdge, ...]


@dataclass(frozen=True, slots=True)
class ExportPlan:
    options: ExportOptions
    journeys: tuple[Journey, ...]
    legs: tuple[ExportLeg, ...]
    token: str

    @property
    def edge_count(self) -> int:
        return sum(len(leg.edges) for leg in self.legs)

    @property
    def unique_edge_count(self) -> int:
        return len({edge.coverage_key for leg in self.legs for edge in leg.edges})

    @property
    def distance_m(self) -> float:
        if self.options.mode == "coverage":
            seen: set[str] = set()
            total = 0.0
            for leg in self.legs:
                for edge in leg.edges:
                    if edge.coverage_key not in seen:
                        seen.add(edge.coverage_key)
                        total += edge.distance_m
            return total
        return sum(edge.distance_m for leg in self.legs for edge in leg.edges)


def _edge_coordinates(
    edge: RouteEdge, reversed_edge: bool
) -> tuple[tuple[float, float], ...]:
    geometry = wkb.loads(edge.geometry_wkb)
    if not isinstance(geometry, LineString) or len(geometry.coords) < 2:
        raise ExportValidationError(f"区间 {edge.id} 的几何无效")
    coordinates = tuple((float(lon), float(lat)) for lon, lat in geometry.coords)
    return coordinates[::-1] if reversed_edge else coordinates


def _snapshot_coordinates(
    snapshot: RailJourneyEdgeSnapshot,
) -> tuple[tuple[float, float], ...]:
    geometry = wkb.loads(snapshot.geometry_wkb)
    if not isinstance(geometry, LineString) or len(geometry.coords) < 2:
        raise ExportValidationError(f"铁路快照 {snapshot.id} 的几何无效")
    if hashlib.sha256(snapshot.geometry_wkb).hexdigest() != snapshot.geometry_sha256:
        raise ExportValidationError(f"铁路快照 {snapshot.id} 的几何校验和不匹配")
    return tuple((float(lon), float(lat)) for lon, lat in geometry.coords)


def _geometry_sha256(coordinates: tuple[tuple[float, float], ...]) -> str:
    payload = [list(coordinate) for coordinate in coordinates]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


def create_export_plan(db: Session, options: ExportOptions) -> ExportPlan:
    statement = select(Journey).order_by(Journey.id)
    if options.journey_ids:
        statement = statement.where(Journey.id.in_(options.journey_ids))
    if options.city_id is not None or options.line_id is not None:
        statement = statement.join(JourneyLeg)
        if options.city_id is not None:
            statement = statement.where(JourneyLeg.city_id == options.city_id)
        if options.line_id is not None:
            statement = statement.where(JourneyLeg.line_id == options.line_id)
        statement = statement.distinct()
    if options.traveled_from is not None:
        statement = statement.where(Journey.traveled_at >= options.traveled_from)
    if options.traveled_to is not None:
        statement = statement.where(Journey.traveled_at <= options.traveled_to)
    journeys = tuple(db.scalars(statement).all())
    if options.journey_ids:
        missing_ids = sorted(
            set(options.journey_ids) - {journey.id for journey in journeys}
        )
        if missing_ids:
            raise ExportValidationError(
                f"所选行程不存在或不符合筛选条件：{', '.join(map(str, missing_ids))}"
            )
    legs: list[ExportLeg] = []
    for journey in journeys:
        journey_legs = db.scalars(
            select(JourneyLeg)
            .where(JourneyLeg.journey_id == journey.id)
            .order_by(JourneyLeg.leg_no)
        ).all()
        for leg in journey_legs:
            if leg.transport_mode == "rail":
                if options.city_id is not None or options.line_id is not None:
                    continue
                if leg.resolution_status != "resolved":
                    raise ExportValidationError(f"行程 {journey.journey_code} 尚未解析")
                snapshot_rows = db.execute(
                    select(RailJourneyEdgeSnapshot, RailDatasetVersion)
                    .join(
                        RailDatasetVersion,
                        RailDatasetVersion.id
                        == RailJourneyEdgeSnapshot.rail_dataset_version_id,
                    )
                    .where(RailJourneyEdgeSnapshot.journey_leg_id == leg.id)
                    .order_by(RailJourneyEdgeSnapshot.order_no)
                ).all()
                if not snapshot_rows:
                    raise ExportValidationError(
                        f"行程 {journey.journey_code} 没有铁路几何快照"
                    )
                rail_dataset_ids = {dataset.id for _, dataset in snapshot_rows}
                if len(rail_dataset_ids) != 1:
                    raise ExportValidationError(
                        f"行程 {journey.journey_code} 混用了多个铁路图版本"
                    )
                rail_dataset = snapshot_rows[0][1]
                rail_edges = tuple(
                    ExportEdge(
                        edge_id=snapshot.id,
                        coverage_key=(
                            f"rail:{rail_dataset.id}:{snapshot.osm_way_id}:"
                            f"{snapshot.geometry_sha256}"
                        ),
                        reversed=snapshot.reversed,
                        from_station_id=None,
                        to_station_id=None,
                        distance_m=snapshot.distance_m,
                        coordinates=_snapshot_coordinates(snapshot),
                    )
                    for snapshot, _ in snapshot_rows
                )
                legs.append(
                    ExportLeg(
                        journey_id=journey.id,
                        journey_code=journey.journey_code,
                        leg_no=leg.leg_no,
                        transport_mode="rail",
                        dataset_version_id=rail_dataset.id,
                        graph_version=rail_dataset.graph_version,
                        profile_version=rail_dataset.profile_version,
                        candidate_digest=leg.candidate_digest,
                        source_geometry_sha256=_geometry_sha256(
                            _join_edges(rail_edges)
                        ),
                        edges=rail_edges,
                    )
                )
                continue
            if leg.transport_mode != "metro" or leg.dataset_version_id is None:
                raise ExportValidationError(
                    f"行程 {journey.journey_code} 的交通方式无效"
                )
            if options.city_id is not None and leg.city_id != options.city_id:
                continue
            if options.line_id is not None and leg.line_id != options.line_id:
                continue
            if leg.resolution_status != "resolved":
                raise ExportValidationError(f"行程 {journey.journey_code} 尚未解析")
            rows = db.execute(
                select(JourneyLegEdge, RouteEdge, RouteVariant.quality_status)
                .join(RouteEdge, RouteEdge.id == JourneyLegEdge.route_edge_id)
                .join(RouteVariant, RouteVariant.id == RouteEdge.route_variant_id)
                .where(JourneyLegEdge.journey_leg_id == leg.id)
                .order_by(JourneyLegEdge.order_no)
            ).all()
            if not rows:
                raise ExportValidationError(f"行程 {journey.journey_code} 没有区间")
            export_edges_list: list[ExportEdge] = []
            for link, edge, variant_quality_status in rows:
                if edge.quality_status != "ready" or variant_quality_status != "ready":
                    raise ExportValidationError(
                        f"行程 {journey.journey_code} 的区间 {edge.id} 未通过质量门禁"
                    )
                export_edges_list.append(
                    ExportEdge(
                        edge_id=edge.id,
                        coverage_key=f"metro:{leg.dataset_version_id}:{edge.id}",
                        reversed=link.reversed,
                        from_station_id=(
                            edge.to_station_id
                            if link.reversed
                            else edge.from_station_id
                        ),
                        to_station_id=(
                            edge.from_station_id
                            if link.reversed
                            else edge.to_station_id
                        ),
                        distance_m=edge.distance_m,
                        coordinates=_edge_coordinates(edge, link.reversed),
                    )
                )
            export_edges = tuple(export_edges_list)
            legs.append(
                ExportLeg(
                    journey_id=journey.id,
                    journey_code=journey.journey_code,
                    leg_no=leg.leg_no,
                    transport_mode="metro",
                    dataset_version_id=leg.dataset_version_id,
                    graph_version=None,
                    profile_version=None,
                    candidate_digest=leg.candidate_digest,
                    source_geometry_sha256=None,
                    edges=export_edges,
                )
            )
    token_payload = {
        "options": {
            "mode": options.mode,
            "max_segment_length_m": options.max_segment_length_m,
            "rail_max_segment_length_m": options.rail_max_segment_length_m,
            "journey_ids": options.journey_ids,
            "city_id": options.city_id,
            "line_id": options.line_id,
            "traveled_from": (
                options.traveled_from.isoformat() if options.traveled_from else None
            ),
            "traveled_to": options.traveled_to.isoformat()
            if options.traveled_to
            else None,
        },
        "journeys": [
            [journey.id, journey.updated_at.isoformat()] for journey in journeys
        ],
        "legs": [
            [
                leg.journey_id,
                leg.leg_no,
                leg.transport_mode,
                leg.dataset_version_id,
                leg.graph_version,
                leg.profile_version,
                leg.candidate_digest,
                leg.source_geometry_sha256,
                [
                    [edge.edge_id, edge.coverage_key, edge.reversed]
                    for edge in leg.edges
                ],
            ]
            for leg in legs
        ],
    }
    digest = hashlib.sha256(
        json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ExportPlan(
        options=options,
        journeys=journeys,
        legs=tuple(legs),
        token=f"sha256:{digest}",
    )


def _densify(
    coordinates: tuple[tuple[float, float], ...], spacing_m: int | None
) -> tuple[tuple[float, float], ...]:
    if spacing_m is None:
        return coordinates
    line = LineString(coordinates)
    center = line.centroid
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={center.y:.12f} +lon_0={center.x:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    to_metric = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    metric = transform(to_metric.transform, line).segmentize(spacing_m)
    result = transform(to_wgs84.transform, metric)
    if not isinstance(result, LineString):
        raise ExportValidationError("轨迹加密失败")
    return tuple((float(lon), float(lat)) for lon, lat in result.coords)


def _join_edges(edges: tuple[ExportEdge, ...]) -> tuple[tuple[float, float], ...]:
    coordinates: list[tuple[float, float]] = []
    for edge in edges:
        if not coordinates:
            coordinates.extend(edge.coordinates)
        elif coordinates[-1] == edge.coordinates[0]:
            coordinates.extend(edge.coordinates[1:])
        else:
            _, _, gap_m = _GEOD.inv(*coordinates[-1], *edge.coordinates[0])
            if gap_m > 5:
                raise ExportValidationError(f"区间 {edge.edge_id} 与前一区间不连续")
            coordinates.extend(edge.coordinates[1:])
    deduplicated = [coordinates[0]]
    for coordinate in coordinates[1:]:
        if coordinate != deduplicated[-1]:
            deduplicated.append(coordinate)
    return tuple(deduplicated)


def _validate_segment(coordinates: tuple[tuple[float, float], ...]) -> None:
    if len(coordinates) < 2 or len(set(coordinates)) < 2:
        raise ExportValidationError("每个 GPX 轨迹段至少需要两个不同点")
    for lon, lat in coordinates:
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ExportValidationError("GPX 坐标超出 WGS-84 范围")
    for previous, current in pairwise(coordinates):
        _, _, distance_m = _GEOD.inv(*previous, *current)
        if distance_m > 20_000:
            raise ExportValidationError("GPX 相邻轨迹点跳跃距离超过 20 公里")


@lru_cache
def _gpx_schema() -> etree.XMLSchema:
    schema_path = Path(__file__).with_name("gpx.xsd")
    return etree.XMLSchema(etree.parse(schema_path))


def validate_gpx(content: bytes) -> None:
    document = etree.fromstring(content)
    if not _gpx_schema().validate(document):
        message = str(_gpx_schema().error_log) or "未知错误"
        raise ExportValidationError(f"GPX 1.1 XSD 校验失败：{message}")


def track_segments(
    plan: ExportPlan,
) -> list[tuple[str, list[tuple[tuple[float, float], ...]]]]:
    if plan.options.mode == "journeys":
        tracks: list[tuple[str, list[tuple[tuple[float, float], ...]]]] = []
        for journey in plan.journeys:
            journey_legs = [leg for leg in plan.legs if leg.journey_id == journey.id]
            segments = [
                _densify(
                    _join_edges(leg.edges),
                    (
                        plan.options.rail_max_segment_length_m
                        if leg.transport_mode == "rail"
                        else plan.options.max_segment_length_m
                    ),
                )
                for leg in journey_legs
            ]
            tracks.append((journey.journey_code, segments))
        return tracks

    seen: set[str] = set()
    coverage_edge_groups: list[tuple[Literal["metro", "rail"], list[ExportEdge]]] = []
    for leg in plan.legs:
        current_group: list[ExportEdge] = []
        for edge in leg.edges:
            if edge.coverage_key in seen:
                if current_group:
                    coverage_edge_groups.append((leg.transport_mode, current_group))
                    current_group = []
                continue
            seen.add(edge.coverage_key)
            if current_group:
                _, _, gap_m = _GEOD.inv(
                    *current_group[-1].coordinates[-1], *edge.coordinates[0]
                )
                if gap_m > 5:
                    coverage_edge_groups.append((leg.transport_mode, current_group))
                    current_group = []
            current_group.append(edge)
        if current_group:
            coverage_edge_groups.append((leg.transport_mode, current_group))
    coverage_segments = [
        _densify(
            _join_edges(tuple(group)),
            (
                plan.options.rail_max_segment_length_m
                if transport_mode == "rail"
                else plan.options.max_segment_length_m
            ),
        )
        for transport_mode, group in coverage_edge_groups
    ]
    return [("Transit2Fog coverage", coverage_segments)] if coverage_segments else []


def render_gpx(plan: ExportPlan) -> bytes:
    nsmap = cast(
        dict[str, str],
        {
            None: GPX_NAMESPACE,
            "xsi": XSI_NAMESPACE,
            "t2f-rail": TRANSIT2FOG_RAIL_NAMESPACE,
        },
    )
    root = etree.Element(
        f"{{{GPX_NAMESPACE}}}gpx",
        nsmap=nsmap,
        version="1.1",
        creator="Transit2Fog",
    )
    root.set(
        f"{{{XSI_NAMESPACE}}}schemaLocation",
        f"{GPX_NAMESPACE} https://www.topografix.com/GPX/1/1/gpx.xsd",
    )
    metadata = etree.SubElement(root, f"{{{GPX_NAMESPACE}}}metadata")
    etree.SubElement(metadata, f"{{{GPX_NAMESPACE}}}name").text = "Transit2Fog export"
    has_rail = any(leg.transport_mode == "rail" for leg in plan.legs)
    rail_graph_versions = sorted(
        {
            leg.graph_version
            for leg in plan.legs
            if leg.transport_mode == "rail" and leg.graph_version is not None
        }
    )
    rail_profile_versions = sorted(
        {
            leg.profile_version
            for leg in plan.legs
            if leg.transport_mode == "rail" and leg.profile_version is not None
        }
    )
    description = (
        "Locally generated from saved CPTOND metro edges and immutable "
        "OpenStreetMap railway snapshots; no synthetic time or elevation. "
        f"Rail graph versions: {', '.join(rail_graph_versions)}; "
        f"profile versions: {', '.join(rail_profile_versions)}."
        if has_rail
        else _METRO_GPX_DESCRIPTION
    )
    etree.SubElement(metadata, f"{{{GPX_NAMESPACE}}}desc").text = description
    if has_rail:
        link = etree.SubElement(
            metadata,
            f"{{{GPX_NAMESPACE}}}link",
            href="https://www.openstreetmap.org/copyright",
        )
        etree.SubElement(
            link, f"{{{GPX_NAMESPACE}}}text"
        ).text = "© OpenStreetMap contributors"
        extensions = etree.SubElement(metadata, f"{{{GPX_NAMESPACE}}}extensions")
        for leg in plan.legs:
            if leg.transport_mode != "rail" or leg.source_geometry_sha256 is None:
                continue
            etree.SubElement(
                extensions,
                f"{{{TRANSIT2FOG_RAIL_NAMESPACE}}}snapshot",
                journeyId=str(leg.journey_id),
                legNo=str(leg.leg_no),
                railDatasetVersionId=str(leg.dataset_version_id),
                graphVersion=leg.graph_version or "unknown",
                profileVersion=leg.profile_version or "unknown",
                candidateDigest=leg.candidate_digest,
                sourceGeometrySha256=leg.source_geometry_sha256,
            )
    for name, segments in track_segments(plan):
        if not segments:
            continue
        track = etree.SubElement(root, f"{{{GPX_NAMESPACE}}}trk")
        etree.SubElement(track, f"{{{GPX_NAMESPACE}}}name").text = name
        for coordinates in segments:
            _validate_segment(coordinates)
            segment = etree.SubElement(track, f"{{{GPX_NAMESPACE}}}trkseg")
            previous: tuple[float, float] | None = None
            for lon, lat in coordinates:
                current = (round(lon, 7), round(lat, 7))
                if current == previous:
                    continue
                etree.SubElement(
                    segment,
                    f"{{{GPX_NAMESPACE}}}trkpt",
                    lat=f"{current[1]:.7f}",
                    lon=f"{current[0]:.7f}",
                )
                previous = current
            if len(segment) < 2:
                raise ExportValidationError("轨迹精度处理后少于两个不同点")
    content = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )
    validate_gpx(content)
    return content
