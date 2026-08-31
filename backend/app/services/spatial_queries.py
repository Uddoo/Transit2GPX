from __future__ import annotations

from sqlalchemy import Integer, text
from sqlalchemy.sql.selectable import Subquery

BBox = tuple[float, float, float, float]


def station_ids_in_bbox(bbox: BBox) -> Subquery:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        text(
            "SELECT id FROM station_spatial "
            "WHERE min_lon <= :station_max_lon AND max_lon >= :station_min_lon "
            "AND min_lat <= :station_max_lat AND max_lat >= :station_min_lat"
        )
        .bindparams(
            station_min_lon=min_lon,
            station_min_lat=min_lat,
            station_max_lon=max_lon,
            station_max_lat=max_lat,
        )
        .columns(id=Integer)
        .subquery("visible_station_ids")
    )


def route_variant_ids_in_bbox(bbox: BBox) -> Subquery:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        text(
            "SELECT DISTINCT edge.route_variant_id AS id "
            "FROM route_edge AS edge "
            "JOIN route_edge_spatial AS spatial ON spatial.id = edge.id "
            "WHERE spatial.min_lon <= :edge_max_lon "
            "AND spatial.max_lon >= :edge_min_lon "
            "AND spatial.min_lat <= :edge_max_lat "
            "AND spatial.max_lat >= :edge_min_lat"
        )
        .bindparams(
            edge_min_lon=min_lon,
            edge_min_lat=min_lat,
            edge_max_lon=max_lon,
            edge_max_lat=max_lat,
        )
        .columns(id=Integer)
        .subquery("visible_route_variant_ids")
    )
