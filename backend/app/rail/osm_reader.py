"""Read station geometries directly from OSM, without GDAL/GeoPandas/Pandas."""

from pathlib import Path
from typing import Any

import osmium  # type: ignore[import-untyped]
from shapely import from_wkb
from shapely.geometry import GeometryCollection, Point
from shapely.geometry.base import BaseGeometry

from app.rail.importer import (
    RailImportError,
    RailStationRecord,
    _aliases,
    _eligible_station,
    _representative_coordinate,
)


def _record(
    kind: str, osm_id: int, tags: dict[str, str], geometry: BaseGeometry
) -> RailStationRecord | None:
    name = tags.get("name:zh-Hans") or tags.get("name:zh") or tags.get("name")
    coordinate = _representative_coordinate(geometry)
    if not name or not coordinate or not _eligible_station(tags):
        return None
    city = tags.get("addr:city") or tags.get("is_in:city")
    flags: list[dict[str, Any]] = []
    if not city:
        flags.append({"code": "city_missing", "message": "OSM 未提供城市字段。"})
    if kind != "node":
        flags.append(
            {"code": "representative_point", "message": "面或关系车站使用内部代表点。"}
        )
    return RailStationRecord(
        osm_type=kind,
        osm_id=osm_id,
        name_cn=name,
        name_en=tags.get("name:en"),
        station_code=tags.get("railway:ref")
        or tags.get("ref:cr")
        or tags.get("uic_ref")
        or tags.get("ref"),
        city_name=city,
        province_name=tags.get("addr:province") or tags.get("is_in:province"),
        lon=coordinate[0],
        lat=coordinate[1],
        aliases=_aliases(tags, name),
        quality_flags=tuple(flags),
    )


def read_station_records(path: Path) -> list[RailStationRecord]:
    factory = osmium.geom.WKBFactory()
    records: dict[tuple[str, int], RailStationRecord] = {}
    relations: dict[int, list[tuple[str, int]]] = {}
    station_relations: dict[int, dict[str, str]] = {}
    station_filter = osmium.filter.TagFilter(
        ("railway", "station"), ("railway", "halt"), ("public_transport", "station")
    )
    for entity in osmium.FileProcessor(path).with_areas().with_filter(station_filter):
        tags = dict(entity.tags)
        if not _eligible_station(tags):
            continue
        geometry: BaseGeometry | None = None
        if isinstance(entity, osmium.osm.Node) and entity.location.valid():
            kind, osm_id = "node", entity.id
            geometry = Point(entity.location.lon, entity.location.lat)
        elif isinstance(entity, osmium.osm.Area):
            kind, osm_id = "way" if entity.from_way() else "relation", entity.orig_id()
            geometry = from_wkb(factory.create_multipolygon(entity))
        elif isinstance(entity, osmium.osm.Relation):
            relations[entity.id] = [
                (member.type, member.ref) for member in entity.members
            ]
            station_relations[entity.id] = tags
        if geometry is not None:
            record = _record(kind, osm_id, tags, geometry)
            if record:
                records[(kind, osm_id)] = record
    # Multipolygon relations were handled as Areas. Assemble other station
    # relations from their actual members instead of silently dropping them.
    station_relations = {
        key: tags
        for key, tags in station_relations.items()
        if ("relation", key) not in records
    }
    if station_relations:
        for _ in range(8):
            missing = {
                ref
                for members in relations.values()
                for kind, ref in members
                if kind == "r" and ref not in relations
            }
            if not missing:
                break
            for entity in osmium.FileProcessor(path, osmium.osm.RELATION):
                if isinstance(entity, osmium.osm.Relation) and entity.id in missing:
                    relations[entity.id] = [
                        (member.type, member.ref) for member in entity.members
                    ]
            if missing.difference(relations):
                raise RailImportError("铁路站点关系引用了 PBF 中不存在的关系。")
        else:
            raise RailImportError("铁路站点关系嵌套超过支持的 8 层。")
        needed = {
            member
            for members in relations.values()
            for member in members
            if member[0] in {"n", "w"}
        }
        geometries: dict[tuple[str, int], BaseGeometry] = {}
        for entity in osmium.FileProcessor(path).with_locations():
            key = (entity.type_str(), entity.id)
            if key not in needed:
                continue
            if isinstance(entity, osmium.osm.Node) and entity.location.valid():
                geometries[key] = Point(entity.location.lon, entity.location.lat)
            elif isinstance(entity, osmium.osm.Way):
                geometries[key] = from_wkb(factory.create_linestring(entity))

        def collect(key: int, seen: frozenset[int]) -> BaseGeometry:
            if key in seen:
                raise RailImportError("铁路站点关系存在循环引用。")
            children = []
            for kind, ref in relations[key]:
                if kind == "r":
                    children.append(collect(ref, seen | {key}))
                elif (kind, ref) in geometries:
                    children.append(geometries[(kind, ref)])
            if not children:
                raise RailImportError("铁路站点关系缺少可用几何，不能生成站点索引。")
            return GeometryCollection(children)

        for osm_id, tags in station_relations.items():
            if record := _record(
                "relation", osm_id, tags, collect(osm_id, frozenset())
            ):
                records[("relation", osm_id)] = record
    return list(records.values())
