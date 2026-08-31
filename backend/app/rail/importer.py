from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio  # type: ignore[import-untyped]
from pyogrio.errors import DataLayerError  # type: ignore[import-untyped]
from shapely.geometry.base import BaseGeometry
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import RailDatasetVersion, RailStation, RailStationAlias
from app.matching.names import normalize_station_name, pinyin_keys

_GRAPH_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_HSTORE_ITEM_RE = re.compile(r'"((?:\\.|[^"])*)"=>"((?:\\.|[^"])*)"')
_OSM_WHERE = (
    "name IS NOT NULL AND ("
    'other_tags LIKE \'%"railway"=>"station"%\' OR '
    'other_tags LIKE \'%"railway"=>"halt"%\' OR '
    'other_tags LIKE \'%"public_transport"=>"station"%\')'
)
_OSM_LAYERS = (
    ("points", "node"),
    ("multipolygons", "area"),
    ("other_relations", "relation"),
)
_ALIAS_TAGS = {
    "alt_name": "alternate_name",
    "old_name": "former_name",
    "official_name": "official_name",
    "short_name": "short_name",
    "name:zh": "zh_name",
    "name:zh-Hans": "zh_hans_name",
    "name:en": "en_name",
}


class RailImportError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RailStationRecord:
    osm_type: str
    osm_id: int
    name_cn: str
    name_en: str | None
    station_code: str | None
    city_name: str | None
    province_name: str | None
    lon: float
    lat: float
    aliases: tuple[tuple[str, str], ...]
    quality_flags: tuple[dict[str, Any], ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def active_graph_path(graph_root: Path) -> Path:
    legacy_selector = graph_root / "active"
    json_selector = graph_root / "active.json"
    legacy_exists = legacy_selector.exists() or legacy_selector.is_symlink()
    json_exists = json_selector.exists()
    if legacy_exists and json_exists:
        raise RailImportError("铁路 active 图版本指针存在冲突。")
    if legacy_exists:
        if not legacy_selector.is_symlink():
            raise RailImportError("铁路 active 图版本指针不是受支持的 selector。")
        try:
            resolved = legacy_selector.resolve(strict=True)
        except OSError as error:
            raise RailImportError("铁路 active 图版本指针已经失效。") from error
    elif json_exists:
        try:
            selector_payload: Any = json.loads(
                json_selector.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise RailImportError("铁路 active 图版本指针不是有效 JSON。") from error
        version = (
            selector_payload.get("graph_version")
            if isinstance(selector_payload, dict)
            else None
        )
        if (
            not isinstance(version, str)
            or not _GRAPH_VERSION_RE.fullmatch(version)
            or version.startswith(".")
        ):
            raise RailImportError("铁路 active 图版本指针超出图数据目录。")
        resolved = (graph_root / version).resolve(strict=False)
        if not resolved.is_dir():
            raise RailImportError("铁路 active 图版本指针已经失效。")
    else:
        raise RailImportError("铁路 active 图版本指针不存在。")
    if resolved.parent != graph_root.resolve():
        raise RailImportError("铁路 active 图版本指针超出图数据目录。")
    return resolved


def resolve_graph_path(graph_root: Path, graph_version: str) -> Path:
    if not _GRAPH_VERSION_RE.fullmatch(graph_version) or graph_version.startswith("."):
        raise RailImportError("铁路图版本名包含不允许的字符。")
    graph_path = (
        active_graph_path(graph_root)
        if graph_version == "active"
        else (graph_root / graph_version).resolve(strict=False)
    )
    if graph_path.parent != graph_root.resolve() or not graph_path.is_dir():
        raise RailImportError("铁路图版本目录不存在或超出图数据目录。")
    return graph_path


def load_graph_metadata(graph_root: Path, graph_version: str) -> dict[str, Any]:
    graph_path = resolve_graph_path(graph_root, graph_version)
    metadata_path = graph_path / "transit2fog-graph.json"
    if not metadata_path.exists():
        metadata_path = graph_path / "metro2fog-graph.json"
    try:
        payload: Any = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RailImportError("铁路图元数据不存在或不是有效 JSON。") from error
    if not isinstance(payload, dict) or payload.get("graph_version") != graph_path.name:
        raise RailImportError("铁路图元数据与所选目录版本不一致。")
    if not isinstance(
        payload.get("graph_version"), str
    ) or not _GRAPH_VERSION_RE.fullmatch(payload["graph_version"]):
        raise RailImportError("铁路图元数据缺少有效的实际版本。")
    required = (
        "pbf_sha256",
        "profile_version",
        "openrailrouting_commit",
        "graphhopper_version",
        "source_timestamp",
        "extract_region",
        "license",
    )
    if any(
        not isinstance(payload.get(field), str) or not payload[field]
        for field in required
    ):
        raise RailImportError("铁路图元数据缺少 PBF、Profile 或许可字段。")
    return payload


def prepare_rail_dataset(
    db: Session,
    *,
    graph_root: Path,
    graph_version: str,
) -> RailDatasetVersion:
    metadata = load_graph_metadata(graph_root, graph_version)
    actual_graph_version = str(metadata["graph_version"])
    existing = db.scalar(
        select(RailDatasetVersion).where(
            RailDatasetVersion.graph_version == actual_graph_version
        )
    )
    if existing is not None:
        return existing
    dataset = RailDatasetVersion(
        source_name="OpenStreetMap/Geofabrik",
        source_url=str(metadata.get("source_url") or "local-pbf"),
        source_timestamp=str(metadata.get("source_timestamp") or "unknown"),
        pbf_checksum=str(metadata["pbf_sha256"]),
        extract_region=str(metadata.get("extract_region") or "unspecified"),
        graph_version=actual_graph_version,
        profile_version=str(metadata["profile_version"]),
        openrailrouting_version=str(
            metadata.get("openrailrouting_commit") or "unknown"
        ),
        graphhopper_version=str(metadata.get("graphhopper_version") or "unknown"),
        license=str(metadata["license"]),
        status="staging",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def _unescape_hstore(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def parse_hstore(value: object) -> dict[str, str]:
    if not isinstance(value, str):
        return {}
    return {
        _unescape_hstore(key): _unescape_hstore(item)
        for key, item in _HSTORE_ITEM_RE.findall(value)
    }


def _text(value: object) -> str | None:
    if (
        value is None
        or value is pd.NA
        or (isinstance(value, float) and math.isnan(value))
    ):
        return None
    normalized = str(value).strip()
    return normalized or None


def _eligible_station(tags: dict[str, str]) -> bool:
    railway = tags.get("railway")
    train = tags.get("train")
    if railway not in {"station", "halt"} and not (
        tags.get("public_transport") == "station" and train != "no"
    ):
        return False
    non_national = any(
        tags.get(key) in {"yes", "only"}
        for key in ("subway", "tram", "light_rail", "monorail")
    ) or tags.get("station") in {"subway", "light_rail", "monorail"}
    return train == "yes" or not non_national


def _representative_coordinate(geometry: object) -> tuple[float, float] | None:
    if not isinstance(geometry, BaseGeometry) or geometry.is_empty:
        return None
    point = (
        geometry if geometry.geom_type == "Point" else geometry.representative_point()
    )
    if not (-180 <= point.x <= 180 and -90 <= point.y <= 90):
        return None
    return float(point.x), float(point.y)


def _osm_identity(row: pd.Series[Any], layer_kind: str) -> tuple[str, int] | None:
    if layer_kind == "node":
        osm_id = _text(row.get("osm_id"))
        return ("node", int(osm_id)) if osm_id else None
    if layer_kind == "relation":
        osm_id = _text(row.get("osm_id"))
        return ("relation", int(osm_id)) if osm_id else None
    relation_id = _text(row.get("osm_id"))
    way_id = _text(row.get("osm_way_id"))
    if relation_id:
        return "relation", int(relation_id)
    return ("way", int(way_id)) if way_id else None


def _aliases(tags: dict[str, str], primary_name: str) -> tuple[tuple[str, str], ...]:
    primary_key = normalize_station_name(primary_name)
    aliases: dict[tuple[str, str], tuple[str, str]] = {}
    for tag, alias_type in _ALIAS_TAGS.items():
        for alias in tags.get(tag, "").split(";"):
            value = alias.strip()
            normalized = normalize_station_name(value)
            if value and normalized and normalized != primary_key:
                aliases[(normalized, alias_type)] = (value, alias_type)
    return tuple(aliases.values())


def records_from_frame(
    frame: gpd.GeoDataFrame,
    *,
    layer_kind: str,
) -> list[RailStationRecord]:
    records: list[RailStationRecord] = []
    for _, row in frame.iterrows():
        tags = parse_hstore(row.get("other_tags"))
        if not _eligible_station(tags):
            continue
        identity = _osm_identity(row, layer_kind)
        coordinate = _representative_coordinate(row.get("geometry"))
        primary_name = (
            tags.get("name:zh-Hans") or tags.get("name:zh") or _text(row.get("name"))
        )
        if identity is None or coordinate is None or not primary_name:
            continue
        code = (
            tags.get("railway:ref")
            or tags.get("ref:cr")
            or tags.get("uic_ref")
            or _text(row.get("ref"))
        )
        city = tags.get("addr:city") or tags.get("is_in:city")
        province = tags.get("addr:province") or tags.get("is_in:province")
        flags: list[dict[str, Any]] = []
        if not city:
            flags.append({"code": "city_missing", "message": "OSM 未提供城市字段。"})
        if identity[0] != "node":
            flags.append(
                {
                    "code": "representative_point",
                    "message": "面或关系车站使用内部代表点。",
                }
            )
        records.append(
            RailStationRecord(
                osm_type=identity[0],
                osm_id=identity[1],
                name_cn=primary_name,
                name_en=tags.get("name:en"),
                station_code=code,
                city_name=city,
                province_name=province,
                lon=coordinate[0],
                lat=coordinate[1],
                aliases=_aliases(tags, primary_name),
                quality_flags=tuple(flags),
            )
        )
    return records


FrameReader = Callable[..., gpd.GeoDataFrame]


def read_rail_station_records(
    pbf_path: Path,
    *,
    frame_reader: FrameReader = pyogrio.read_dataframe,
) -> list[RailStationRecord]:
    by_identity: dict[tuple[str, int], RailStationRecord] = {}
    for layer, layer_kind in _OSM_LAYERS:
        try:
            frame = frame_reader(pbf_path, layer=layer, where=_OSM_WHERE)
        except (DataLayerError, ValueError):
            continue
        for record in records_from_frame(frame, layer_kind=layer_kind):
            by_identity.setdefault((record.osm_type, record.osm_id), record)
    return list(by_identity.values())


def import_rail_station_records(
    db: Session,
    *,
    dataset: RailDatasetVersion,
    records: Iterable[RailStationRecord],
) -> int:
    if dataset.status not in {"staging", "building", "failed"}:
        raise RailImportError("就绪或退役的铁路数据版本不能覆盖导入。")
    db.execute(
        delete(RailStation).where(RailStation.rail_dataset_version_id == dataset.id)
    )
    station_rows: list[tuple[RailStation, RailStationRecord]] = []
    for record in records:
        pinyin_full, pinyin_initials = pinyin_keys(record.name_cn)
        station = RailStation(
            rail_dataset_version_id=dataset.id,
            osm_type=record.osm_type,
            osm_id=record.osm_id,
            name_cn=record.name_cn,
            name_en=record.name_en,
            normalized_name=normalize_station_name(record.name_cn),
            pinyin_full=pinyin_full,
            pinyin_initials=pinyin_initials,
            station_code=record.station_code,
            city_name=record.city_name,
            province_name=record.province_name,
            lon=record.lon,
            lat=record.lat,
            match_status="ready",
            quality_flags_json=list(record.quality_flags),
        )
        db.add(station)
        station_rows.append((station, record))
    db.flush()
    for station, record in station_rows:
        for alias, alias_type in record.aliases:
            db.add(
                RailStationAlias(
                    station_id=station.id,
                    alias=alias,
                    normalized_alias=normalize_station_name(alias),
                    alias_type=alias_type,
                    source="OpenStreetMap",
                )
            )
    return len(station_rows)


def execute_rail_import(
    db: Session,
    *,
    dataset_id: int,
    pbf_path: Path,
    frame_reader: FrameReader = pyogrio.read_dataframe,
) -> int:
    dataset = db.get(RailDatasetVersion, dataset_id)
    if dataset is None:
        raise RailImportError("铁路数据导入记录不存在。")
    if not pbf_path.is_file() or not pbf_path.name.endswith(".osm.pbf"):
        raise RailImportError("铁路数据必须是存在的 .osm.pbf 文件。")
    dataset.status = "building"
    dataset.quality_flags_json = []
    db.commit()
    checksum = sha256_file(pbf_path)
    if checksum != dataset.pbf_checksum:
        raise RailImportError("PBF SHA-256 与铁路图元数据不一致。")
    records = read_rail_station_records(pbf_path, frame_reader=frame_reader)
    if not records:
        raise RailImportError("PBF 中没有找到可用的具名国铁客运站。")
    count = import_rail_station_records(db, dataset=dataset, records=records)
    dataset.status = "ready"
    dataset.completed_at = datetime.now(UTC)
    dataset.quality_flags_json = [
        {"code": "station_import_summary", "station_count": count}
    ]
    db.commit()
    return count


def rail_station_count(db: Session, dataset_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(RailStation.id)).where(
                RailStation.rail_dataset_version_id == dataset_id
            )
        )
        or 0
    )
