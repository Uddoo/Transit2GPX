from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

import networkx as nx  # type: ignore[import-untyped]
from shapely import wkb
from shapely.geometry import LineString
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import City, DatasetVersion, Line, RouteEdge, RouteStop, RouteVariant


@dataclass(frozen=True, slots=True)
class ResolvedCandidate:
    candidate_id: str
    digest: str
    dataset_version_id: int
    line_id: int
    route_variant_id: int
    line_name: str
    direction_name: str
    distance_m: float
    station_ids: tuple[int, ...]
    edge_ids: tuple[int, ...]
    reversed_edges: tuple[bool, ...]
    coordinates: tuple[tuple[float, float], ...]
    warnings: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Resolution:
    status: Literal["resolved", "needs_review", "unresolved"]
    candidates: tuple[ResolvedCandidate, ...]


@dataclass(frozen=True, slots=True)
class MultiLineCandidate:
    candidate_id: str
    digest: str
    distance_m: float
    station_ids: tuple[int, ...]
    coordinates: tuple[tuple[float, float], ...]
    line_name: str
    direction_name: str
    warnings: tuple[dict[str, Any], ...]
    legs: tuple[ResolvedCandidate, ...]


@dataclass(frozen=True, slots=True)
class MultiLineResolution:
    status: Literal["needs_review", "unresolved"]
    candidates: tuple[MultiLineCandidate, ...]


def _edge_coordinates(
    edge: RouteEdge, reversed_edge: bool
) -> list[tuple[float, float]]:
    geometry = wkb.loads(edge.geometry_wkb)
    if not isinstance(geometry, LineString):
        return []
    coordinates = [(float(lon), float(lat)) for lon, lat in geometry.coords]
    return coordinates[::-1] if reversed_edge else coordinates


def _candidate(
    *,
    line: Line,
    variant: RouteVariant,
    edges: list[RouteEdge],
    reversed_edges: list[bool],
    start_station_id: int,
    direction_name: str,
) -> ResolvedCandidate | None:
    if not edges:
        return None
    station_ids = [start_station_id]
    coordinates: list[tuple[float, float]] = []
    warnings: list[dict[str, Any]] = list(variant.quality_flags_json)
    for edge, reversed_edge in zip(edges, reversed_edges, strict=True):
        station_ids.append(
            edge.from_station_id if reversed_edge else edge.to_station_id
        )
        edge_coordinates = _edge_coordinates(edge, reversed_edge)
        if not edge_coordinates:
            return None
        if coordinates and coordinates[-1] == edge_coordinates[0]:
            coordinates.extend(edge_coordinates[1:])
        else:
            coordinates.extend(edge_coordinates)
        warnings.extend(edge.quality_flags_json)
    digest_payload = {
        "dataset_version_id": variant.dataset_version_id,
        "route_variant_id": variant.id,
        "edges": [
            [edge.id, reversed_edge]
            for edge, reversed_edge in zip(edges, reversed_edges, strict=True)
        ],
    }
    digest_hex = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ResolvedCandidate(
        candidate_id=f"cand_{digest_hex[:20]}",
        digest=f"sha256:{digest_hex}",
        dataset_version_id=variant.dataset_version_id,
        line_id=line.id,
        route_variant_id=variant.id,
        line_name=line.name_cn,
        direction_name=direction_name,
        distance_m=sum(edge.distance_m for edge in edges),
        station_ids=tuple(station_ids),
        edge_ids=tuple(edge.id for edge in edges),
        reversed_edges=tuple(reversed_edges),
        coordinates=tuple(coordinates),
        warnings=tuple(warnings),
    )


def _contains_via(candidate: ResolvedCandidate, via_station_ids: list[int]) -> bool:
    search_from = 0
    for via_station_id in via_station_ids:
        try:
            search_from = candidate.station_ids.index(via_station_id, search_from) + 1
        except ValueError:
            return False
    return True


def _variant_candidates(
    db: Session,
    *,
    line: Line,
    variant: RouteVariant,
    start_station_id: int,
    end_station_id: int,
) -> list[ResolvedCandidate]:
    route_stops = db.scalars(
        select(RouteStop)
        .where(RouteStop.route_variant_id == variant.id)
        .order_by(RouteStop.source_sequence, RouteStop.id)
    ).all()
    station_ids = [stop.station_id for stop in route_stops]
    if start_station_id not in station_ids or end_station_id not in station_ids:
        return []
    if station_ids.count(start_station_id) > 1 or station_ids.count(end_station_id) > 1:
        return []

    edges = db.scalars(
        select(RouteEdge)
        .where(
            RouteEdge.route_variant_id == variant.id,
            RouteEdge.quality_status == "ready",
        )
        .order_by(RouteEdge.sequence_from, RouteEdge.id)
    ).all()
    edge_by_sequences = {(edge.sequence_from, edge.sequence_to): edge for edge in edges}
    start_index = station_ids.index(start_station_id)
    end_index = station_ids.index(end_station_id)
    results: list[ResolvedCandidate] = []

    if not variant.is_loop:
        low_index, high_index = sorted((start_index, end_index))
        selected: list[RouteEdge] = []
        for index in range(low_index, high_index):
            key = (
                route_stops[index].source_sequence,
                route_stops[index + 1].source_sequence,
            )
            edge = edge_by_sequences.get(key)
            if edge is None:
                return []
            selected.append(edge)
        is_reversed = start_index > end_index
        if is_reversed:
            selected.reverse()
        candidate = _candidate(
            line=line,
            variant=variant,
            edges=selected,
            reversed_edges=[is_reversed] * len(selected),
            start_station_id=start_station_id,
            direction_name=variant.direction_name
            or ("反向" if is_reversed else "正向"),
        )
        return [candidate] if candidate else []

    outgoing_edges: list[RouteEdge] = []
    for index, route_stop in enumerate(route_stops):
        next_stop = route_stops[(index + 1) % len(route_stops)]
        edge = edge_by_sequences.get(
            (route_stop.source_sequence, next_stop.source_sequence)
        )
        if edge is None:
            return []
        outgoing_edges.append(edge)

    forward_edges: list[RouteEdge] = []
    current = start_index
    while current != end_index:
        forward_edges.append(outgoing_edges[current])
        current = (current + 1) % len(route_stops)
    forward = _candidate(
        line=line,
        variant=variant,
        edges=forward_edges,
        reversed_edges=[False] * len(forward_edges),
        start_station_id=start_station_id,
        direction_name=variant.direction_name or "环线源顺序",
    )
    if forward:
        results.append(forward)

    reverse_edges: list[RouteEdge] = []
    current = start_index
    while current != end_index:
        previous = (current - 1) % len(route_stops)
        reverse_edges.append(outgoing_edges[previous])
        current = previous
    reverse_candidate = _candidate(
        line=line,
        variant=variant,
        edges=reverse_edges,
        reversed_edges=[True] * len(reverse_edges),
        start_station_id=start_station_id,
        direction_name="环线逆源顺序",
    )
    if reverse_candidate:
        results.append(reverse_candidate)
    return results


def resolve_line_path(
    db: Session,
    *,
    line_id: int,
    start_station_id: int,
    end_station_id: int,
    direction: str = "auto",
    via_station_ids: list[int] | None = None,
) -> Resolution:
    if start_station_id == end_station_id:
        return Resolution(status="unresolved", candidates=())
    line = db.get(Line, line_id)
    if line is None or line.status != "ready":
        return Resolution(status="unresolved", candidates=())
    variants = db.scalars(
        select(RouteVariant)
        .where(
            RouteVariant.line_id == line_id,
            RouteVariant.quality_status == "ready",
        )
        .order_by(RouteVariant.id)
    ).all()
    candidates: list[ResolvedCandidate] = []
    for variant in variants:
        candidates.extend(
            _variant_candidates(
                db,
                line=line,
                variant=variant,
                start_station_id=start_station_id,
                end_station_id=end_station_id,
            )
        )

    vias = via_station_ids or []
    candidates = [
        candidate for candidate in candidates if _contains_via(candidate, vias)
    ]
    if direction and direction != "auto":
        direction_key = direction.casefold()
        candidates = [
            candidate
            for candidate in candidates
            if direction_key in candidate.direction_name.casefold()
        ]

    unique: dict[tuple[tuple[int, bool], ...], ResolvedCandidate] = {}
    for candidate in candidates:
        key = tuple(zip(candidate.edge_ids, candidate.reversed_edges, strict=True))
        unique[key] = candidate
    resolved = tuple(unique.values())
    if not resolved:
        status: Literal["resolved", "needs_review", "unresolved"] = "unresolved"
    elif len(resolved) == 1 and not resolved[0].warnings:
        status = "resolved"
    else:
        status = "needs_review"
    return Resolution(status=status, candidates=resolved)


def _add_ride_edge(
    graph: nx.DiGraph,
    *,
    source: tuple[int, int],
    target: tuple[int, int],
    edge: RouteEdge,
    variant: RouteVariant,
    line: Line,
    reversed_edge: bool,
) -> None:
    existing = graph.get_edge_data(source, target)
    candidate_key = (edge.distance_m, edge.id, reversed_edge)
    if existing is not None and existing["selection_key"] <= candidate_key:
        return
    graph.add_edge(
        source,
        target,
        weight=edge.distance_m,
        selection_key=candidate_key,
        transfer=False,
        route_edge=edge,
        route_variant=variant,
        line=line,
        reversed=reversed_edge,
    )


def _multiline_candidate(
    graph: nx.DiGraph, path: list[tuple[Any, ...]]
) -> MultiLineCandidate | None:
    nodes = [node for node in path if isinstance(node[0], int)]
    if len(nodes) < 2:
        return None
    groups: list[tuple[Line, RouteVariant, list[RouteEdge], list[bool], int]] = []
    current_line: Line | None = None
    current_variant: RouteVariant | None = None
    current_edges: list[RouteEdge] = []
    current_reversed: list[bool] = []
    current_start_station_id = 0
    for source, target in pairwise(path):
        data = graph.get_edge_data(source, target)
        if data is None or data.get("transfer"):
            if current_line is not None and current_variant is not None:
                groups.append(
                    (
                        current_line,
                        current_variant,
                        current_edges,
                        current_reversed,
                        current_start_station_id,
                    )
                )
            current_line = None
            current_variant = None
            current_edges = []
            current_reversed = []
            continue
        line = data["line"]
        variant = data["route_variant"]
        edge = data["route_edge"]
        reversed_edge = bool(data["reversed"])
        if current_variant is None or current_variant.id != variant.id:
            if current_line is not None and current_variant is not None:
                groups.append(
                    (
                        current_line,
                        current_variant,
                        current_edges,
                        current_reversed,
                        current_start_station_id,
                    )
                )
            current_line = line
            current_variant = variant
            current_edges = []
            current_reversed = []
            current_start_station_id = int(source[0])
        current_edges.append(edge)
        current_reversed.append(reversed_edge)
    if current_line is not None and current_variant is not None:
        groups.append(
            (
                current_line,
                current_variant,
                current_edges,
                current_reversed,
                current_start_station_id,
            )
        )

    legs: list[ResolvedCandidate] = []
    for line, variant, edges, reversed_edges, start_station_id in groups:
        leg = _candidate(
            line=line,
            variant=variant,
            edges=edges,
            reversed_edges=reversed_edges,
            start_station_id=start_station_id,
            direction_name=variant.direction_name or "自动换乘候选",
        )
        if leg is None:
            return None
        legs.append(leg)
    if not legs:
        return None

    coordinates: list[tuple[float, float]] = []
    for leg in legs:
        if coordinates and coordinates[-1] == leg.coordinates[0]:
            coordinates.extend(leg.coordinates[1:])
        else:
            coordinates.extend(leg.coordinates)
    station_ids: list[int] = []
    for node in nodes:
        station_id = int(node[0])
        if not station_ids or station_ids[-1] != station_id:
            station_ids.append(station_id)
    digest_payload = [
        [leg.candidate_id, leg.digest, leg.route_variant_id] for leg in legs
    ]
    digest_hex = hashlib.sha256(
        json.dumps(digest_payload, separators=(",", ":")).encode()
    ).hexdigest()
    line_names: list[str] = []
    for leg in legs:
        if not line_names or line_names[-1] != leg.line_name:
            line_names.append(leg.line_name)
    transfer_count = max(0, len(line_names) - 1)
    warnings = (
        {
            "code": "unspecified_line_requires_confirmation",
            "message": "未指定线路的换乘候选必须人工确认。",
        },
        *(warning for leg in legs for warning in leg.warnings),
    )
    return MultiLineCandidate(
        candidate_id=f"multi_{digest_hex[:20]}",
        digest=f"sha256:{digest_hex}",
        distance_m=sum(leg.distance_m for leg in legs),
        station_ids=tuple(station_ids),
        coordinates=tuple(coordinates),
        line_name=" → ".join(line_names),
        direction_name=f"{transfer_count} 次换乘",
        warnings=warnings,
        legs=tuple(legs),
    )


def resolve_city_path(
    db: Session,
    *,
    city_id: int,
    start_station_id: int,
    end_station_id: int,
    via_station_ids: list[int] | None = None,
    max_candidates: int = 5,
) -> MultiLineResolution:
    if start_station_id == end_station_id:
        return MultiLineResolution(status="unresolved", candidates=())
    rows = db.execute(
        select(RouteEdge, RouteVariant, Line)
        .join(RouteVariant, RouteVariant.id == RouteEdge.route_variant_id)
        .join(Line, Line.id == RouteVariant.line_id)
        .join(City, City.id == Line.city_id)
        .join(DatasetVersion, DatasetVersion.id == City.dataset_version_id)
        .where(
            City.id == city_id,
            City.status == "ready",
            DatasetVersion.status == "ready",
            Line.status == "ready",
            RouteVariant.quality_status == "ready",
            RouteEdge.quality_status == "ready",
        )
        .order_by(Line.id, RouteVariant.id, RouteEdge.sequence_from, RouteEdge.id)
    ).all()
    graph = nx.DiGraph()
    station_lines: dict[int, set[int]] = defaultdict(set)
    for edge, variant, line in rows:
        source = (edge.from_station_id, line.id)
        target = (edge.to_station_id, line.id)
        station_lines[edge.from_station_id].add(line.id)
        station_lines[edge.to_station_id].add(line.id)
        _add_ride_edge(
            graph,
            source=source,
            target=target,
            edge=edge,
            variant=variant,
            line=line,
            reversed_edge=False,
        )
        _add_ride_edge(
            graph,
            source=target,
            target=source,
            edge=edge,
            variant=variant,
            line=line,
            reversed_edge=True,
        )

    for station_id, line_ids in station_lines.items():
        for source_line_id in line_ids:
            for target_line_id in line_ids:
                if source_line_id == target_line_id:
                    continue
                graph.add_edge(
                    (station_id, source_line_id),
                    (station_id, target_line_id),
                    weight=1_000,
                    selection_key=(0, 0, False),
                    transfer=True,
                )

    vias = tuple(via_station_ids or ())
    if any(via_station_id not in station_lines for via_station_id in vias):
        return MultiLineResolution(status="unresolved", candidates=())
    routing_graph = graph
    start_stage = 0
    while start_stage < len(vias) and vias[start_stage] == start_station_id:
        start_stage += 1
    if vias:
        layered_graph = nx.DiGraph()
        for source, target, data in graph.edges(data=True):
            for stage in range(len(vias) + 1):
                next_stage = stage
                while next_stage < len(vias) and int(target[0]) == vias[next_stage]:
                    next_stage += 1
                layered_graph.add_edge(
                    (source[0], source[1], stage),
                    (target[0], target[1], next_stage),
                    **data,
                )
        routing_graph = layered_graph

    source_node: tuple[str, int] = ("source", 0)
    target_node: tuple[str, int] = ("target", 0)
    for line_id in sorted(station_lines.get(start_station_id, ())):
        source_target = (
            (start_station_id, line_id, start_stage)
            if vias
            else (start_station_id, line_id)
        )
        routing_graph.add_edge(
            source_node,
            source_target,
            weight=0,
            selection_key=(0, 0, False),
            transfer=True,
        )
    for line_id in sorted(station_lines.get(end_station_id, ())):
        target_source = (
            (end_station_id, line_id, len(vias)) if vias else (end_station_id, line_id)
        )
        routing_graph.add_edge(
            target_source,
            target_node,
            weight=0,
            selection_key=(0, 0, False),
            transfer=True,
        )
    if source_node not in routing_graph or target_node not in routing_graph:
        return MultiLineResolution(status="unresolved", candidates=())

    candidates: list[MultiLineCandidate] = []
    try:
        paths = nx.shortest_simple_paths(
            routing_graph, source_node, target_node, weight="weight"
        )
        for path in paths:
            candidate = _multiline_candidate(routing_graph, path)
            if candidate is None:
                continue
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return MultiLineResolution(status="unresolved", candidates=())
    if not candidates:
        return MultiLineResolution(status="unresolved", candidates=())
    return MultiLineResolution(status="needs_review", candidates=tuple(candidates))
