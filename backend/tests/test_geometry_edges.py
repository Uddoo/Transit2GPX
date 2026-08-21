from __future__ import annotations

import pytest
from shapely.geometry import LineString, MultiLineString

from app.geometry.edges import (
    GeometryBuildError,
    SourceStop,
    build_loop_edges,
    build_route_edges,
    reverse_line,
)


def test_builds_adjacent_edges_in_source_stop_order() -> None:
    route = LineString([(121.40, 31.20), (121.45, 31.20), (121.50, 31.20)])
    stops = [
        SourceStop(station_id=1, sequence=1, lon=121.40, lat=31.20),
        SourceStop(station_id=2, sequence=2, lon=121.45, lat=31.20),
        SourceStop(station_id=3, sequence=3, lon=121.50, lat=31.20),
    ]

    result = build_route_edges(route, stops)

    assert result.was_reversed is False
    assert [(edge.from_station_id, edge.to_station_id) for edge in result.edges] == [
        (1, 2),
        (2, 3),
    ]
    assert all(4_000 < edge.distance_m < 6_000 for edge in result.edges)
    assert result.edges[0].geometry.coords[0] == pytest.approx((121.40, 31.20))
    assert result.edges[-1].geometry.coords[-1] == pytest.approx((121.50, 31.20))


def test_reorients_route_when_source_sequence_runs_backwards() -> None:
    route = LineString([(121.40, 31.20), (121.45, 31.20), (121.50, 31.20)])
    stops = [
        SourceStop(station_id=3, sequence=1, lon=121.50, lat=31.20),
        SourceStop(station_id=2, sequence=2, lon=121.45, lat=31.20),
        SourceStop(station_id=1, sequence=3, lon=121.40, lat=31.20),
    ]

    result = build_route_edges(route, stops)

    assert result.was_reversed is True
    assert [(edge.from_station_id, edge.to_station_id) for edge in result.edges] == [
        (3, 2),
        (2, 1),
    ]


def test_rejects_disconnected_route_geometry() -> None:
    route = MultiLineString(
        [
            [(121.40, 31.20), (121.42, 31.20)],
            [(121.48, 31.20), (121.50, 31.20)],
        ]
    )
    stops = [
        SourceStop(station_id=1, sequence=1, lon=121.40, lat=31.20),
        SourceStop(station_id=2, sequence=2, lon=121.50, lat=31.20),
    ]

    with pytest.raises(GeometryBuildError, match="不连续") as error:
        build_route_edges(route, stops)

    assert error.value.code == "disconnected_geometry"


def test_reverse_multiline_reverses_parts_and_coordinates() -> None:
    geometry = MultiLineString([[(0, 0), (1, 0)], [(1, 0), (2, 0)]])

    reversed_geometry = reverse_line(geometry)

    assert isinstance(reversed_geometry, MultiLineString)
    assert list(reversed_geometry.geoms[0].coords) == [(2, 0), (1, 0)]
    assert list(reversed_geometry.geoms[1].coords) == [(1, 0), (0, 0)]


def test_loop_builder_creates_closing_edge() -> None:
    route = LineString(
        [
            (121.40, 31.20),
            (121.42, 31.20),
            (121.42, 31.22),
            (121.40, 31.22),
            (121.40, 31.20),
        ]
    )
    stops = [
        SourceStop(station_id=1, sequence=1, lon=121.40, lat=31.20),
        SourceStop(station_id=2, sequence=2, lon=121.42, lat=31.20),
        SourceStop(station_id=3, sequence=3, lon=121.42, lat=31.22),
        SourceStop(station_id=4, sequence=4, lon=121.40, lat=31.22),
    ]

    result = build_loop_edges(route, stops)

    assert len(result.edges) == 4
    assert (result.edges[-1].from_station_id, result.edges[-1].to_station_id) == (
        4,
        1,
    )
