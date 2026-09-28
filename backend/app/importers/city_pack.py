"""Portable, data-only city graphs. No SQL, pickle or GIS file readers in packs."""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from shapely import from_wkb
from sqlalchemy import (
    Boolean,
    Float,
    Integer,
    LargeBinary,
    Select,
    String,
    select,
    update,
)
from sqlalchemy.orm import Session

from app.db.base import AppMeta, Base
from app.db.models import (
    City,
    DatasetVersion,
    Line,
    RouteEdge,
    RouteStop,
    RouteVariant,
    Station,
    StationAlias,
)

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_NETWORK = 128 * 1024 * 1024
TABLES: dict[str, type[Base]] = {
    "cities": City,
    "stations": Station,
    "lines": Line,
    "variants": RouteVariant,
    "stops": RouteStop,
    "edges": RouteEdge,
    "aliases": StationAlias,
}
OMIT = {"dataset_version_id", "city_id"}


class CityPackError(ValueError):
    pass


class PackSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=1000)
    license: str = Field(min_length=1, max_length=200)
    captured_at: str | None = Field(default=None, max_length=40)
    checksum: str = Field(min_length=1, max_length=128)
    importer: str = Field(min_length=1, max_length=40)
    attribution: str = Field(min_length=1, max_length=8000)


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["transit2fog-city-v1"] = "transit2fog-city-v1"
    city_code: str = Field(min_length=1, max_length=100)
    city_name: str = Field(min_length=1, max_length=120)
    network_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    source: PackSource


class PackPreview(BaseModel):
    package_id: str
    manifest: PackManifest
    lines: int
    stations: int
    ready_variants: int
    blocked_variants: int


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fields(model: type[Base]) -> dict[str, Any]:
    return {
        column.name: column
        for column in model.__table__.columns
        if column.name not in OMIT
    }


def _validate_record(model: type[Base], row: dict[str, Any]) -> None:
    fields = _fields(model)
    if row.keys() != fields.keys():
        raise CityPackError(f"{model.__tablename__} 数据字段不符合城市包格式。")
    for name, column in fields.items():
        value = row[name]
        if value is None and column.nullable:
            continue
        kind = column.type
        valid = False
        if isinstance(kind, Boolean):
            valid = type(value) is bool
        elif isinstance(kind, Integer):
            valid = type(value) is int and abs(value) < 2**53
        elif isinstance(kind, Float):
            valid = type(value) in (int, float) and math.isfinite(value)
        elif isinstance(kind, String):
            valid = isinstance(value, str) and len(value) <= (kind.length or 8000)
        elif isinstance(kind, LargeBinary):
            valid = isinstance(value, str) and len(value) <= 16 * 1024 * 1024
            if valid:
                try:
                    geometry = from_wkb(bytes.fromhex(value))
                    valid = (
                        geometry.geom_type in {"LineString", "MultiLineString"}
                        and not geometry.is_empty
                        and geometry.is_valid
                        and not geometry.has_z
                    )
                    if model is RouteEdge:
                        valid = valid and geometry.geom_type == "LineString"
                    x1, y1, x2, y2 = geometry.bounds
                    valid = valid and -180 <= x1 <= x2 <= 180 and -90 <= y1 <= y2 <= 90
                except Exception as error:
                    raise CityPackError("线路几何无效。") from error
        else:  # The only remaining allowed columns are quality flag JSON lists.
            valid = (
                isinstance(value, list)
                and len(value) <= 1000
                and all(isinstance(flag, dict) for flag in value)
            )
        if not valid:
            raise CityPackError(f"城市包字段 {model.__tablename__}.{name} 无效。")
        if name == "id" and value <= 0:
            raise CityPackError("城市包本地编号必须为正整数。")
        if name.endswith("lon") and not -180 <= value <= 180:
            raise CityPackError("经度超出 WGS84 范围。")
        if name.endswith("lat") and not -90 <= value <= 90:
            raise CityPackError("纬度超出 WGS84 范围。")
        if name in {"status", "quality_status"} and value not in {"ready", "blocked"}:
            raise CityPackError("城市包包含尚未完成质量检查的数据。")


def validate_network(
    network: Any, manifest: PackManifest
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(network, dict) or network.keys() != TABLES.keys():
        raise CityPackError("城市包缺少线路网络表。")
    maps: dict[str, dict[int, dict[str, Any]]] = {}
    for name, model in TABLES.items():
        rows = network[name]
        if not isinstance(rows, list) or len(rows) > 100000:
            raise CityPackError("城市包记录数量无效。")
        maps[name] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise CityPackError("城市包记录不是对象。")
            _validate_record(model, row)
            if row["id"] in maps[name]:
                raise CityPackError("城市包存在重复编号。")
            maps[name][row["id"]] = row
    if len(network["cities"]) != 1:
        raise CityPackError("每份城市包必须且只能包含一个城市。")
    city = network["cities"][0]
    if (city["source_city_code"], city["name_cn"], city["status"]) != (
        manifest.city_code,
        manifest.city_name,
        "ready",
    ):
        raise CityPackError("城市包清单与城市记录不一致。")
    foreign = {
        "variants": {"line_id": "lines"},
        "stops": {"route_variant_id": "variants", "station_id": "stations"},
        "edges": {
            "route_variant_id": "variants",
            "from_route_stop_id": "stops",
            "to_route_stop_id": "stops",
            "from_station_id": "stations",
            "to_station_id": "stations",
        },
        "aliases": {"station_id": "stations"},
    }
    for name, fields in foreign.items():
        for row in network[name]:
            if any(row[key] not in maps[target] for key, target in fields.items()):
                raise CityPackError("城市包存在无效的线路或站点引用。")
    edge_counts: dict[int, int] = {}
    for edge in network["edges"]:
        for side, sequence in (("from", "sequence_from"), ("to", "sequence_to")):
            stop = maps["stops"][edge[f"{side}_route_stop_id"]]
            if (
                stop["route_variant_id"],
                stop["station_id"],
                stop["source_sequence"],
            ) != (edge["route_variant_id"], edge[f"{side}_station_id"], edge[sequence]):
                raise CityPackError("城市包线路片段与站序不一致。")
        if edge["distance_m"] <= 0:
            raise CityPackError("城市包线路片段距离无效。")
        geometry = from_wkb(bytes.fromhex(edge["geometry_wkb"]))
        if any(
            abs(a - b) > 1e-7
            for a, b in zip(
                geometry.bounds,
                (edge["min_lon"], edge["min_lat"], edge["max_lon"], edge["max_lat"]),
                strict=True,
            )
        ):
            raise CityPackError("城市包片段包围盒与几何不一致。")
        if edge["quality_status"] == "ready":
            edge_counts[edge["route_variant_id"]] = (
                edge_counts.get(edge["route_variant_id"], 0) + 1
            )
    ready_lines: set[int] = set()
    stops_by_variant: dict[int, list[dict[str, Any]]] = {}
    edges_by_variant: dict[int, set[tuple[int, int]]] = {}
    for stop in network["stops"]:
        stops_by_variant.setdefault(stop["route_variant_id"], []).append(stop)
        if stop["projected_measure_m"] < 0 or stop["projection_error_m"] < 0:
            raise CityPackError("城市包站点投影参数无效。")
    for edge in network["edges"]:
        if edge["quality_status"] == "ready":
            edges_by_variant.setdefault(edge["route_variant_id"], set()).add(
                (edge["sequence_from"], edge["sequence_to"])
            )
    for variant in network["variants"]:
        if variant["quality_status"] == "ready":
            if not edge_counts.get(variant["id"]):
                raise CityPackError("可用线路方向缺少可用片段。")
            stops = sorted(
                stops_by_variant.get(variant["id"], []),
                key=lambda row: row["source_sequence"],
            )
            sequences = [stop["source_sequence"] for stop in stops]
            if len(sequences) < 2 or len(set(sequences)) != len(sequences):
                raise CityPackError("可用线路的站序缺失或重复。")
            expected = set(pairwise(sequences))
            if variant["is_loop"]:
                expected.add((sequences[-1], sequences[0]))
            if edges_by_variant.get(variant["id"]) != expected:
                raise CityPackError("可用线路片段不连续或环线未闭合。")
            if maps["lines"][variant["line_id"]]["status"] != "ready":
                raise CityPackError("可用方向的父线路未通过质量检查。")
            ready_lines.add(variant["line_id"])
    if not ready_lines or any(
        row["status"] == "ready" and row["id"] not in ready_lines
        for row in network["lines"]
    ):
        raise CityPackError("城市包没有完整的可用线路。")
    return network


def read_city_pack(path: Path) -> tuple[PackPreview, dict[str, list[dict[str, Any]]]]:
    try:
        if path.stat().st_size > MAX_ARCHIVE:
            raise CityPackError("城市包超过 32 MiB 限制，请按城市拆分。")
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) != 2 or {item.filename for item in entries} != {
                "manifest.json",
                "network.json",
            }:
                raise CityPackError("城市包只能包含 manifest.json 和 network.json。")
            if (
                archive.getinfo("manifest.json").file_size > 64000
                or archive.getinfo("network.json").file_size > MAX_NETWORK
            ):
                raise CityPackError("城市包解压大小超出限制。")
            manifest = PackManifest.model_validate_json(archive.read("manifest.json"))
            content = archive.read("network.json")
            if hashlib.sha256(content).hexdigest() != manifest.network_sha256:
                raise CityPackError("城市包校验失败，网络数据与清单不匹配。")
            network = validate_network(json.loads(content), manifest)
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        return PackPreview(
            package_id=checksum,
            manifest=manifest,
            lines=len(network["lines"]),
            stations=len(network["stations"]),
            ready_variants=sum(
                row["quality_status"] == "ready" for row in network["variants"]
            ),
            blocked_variants=sum(
                row["quality_status"] == "blocked" for row in network["variants"]
            ),
        ), network
    except CityPackError:
        raise
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError, KeyError) as error:
        raise CityPackError("城市包损坏或格式不受支持。") from error


def export_city_pack(
    db: Session, city_id: int, output: Path, attribution: str
) -> PackPreview:
    city = db.get(City, city_id)
    if city is None or city.status != "ready":
        raise CityPackError("只能导出通过质量门禁的城市。")
    dataset = db.get(DatasetVersion, city.dataset_version_id)
    if dataset is None or dataset.status not in {"ready", "retired"}:
        raise CityPackError("源数据集尚未完成导入。")
    variants = select(RouteVariant.id).where(
        RouteVariant.dataset_version_id == dataset.id,
        RouteVariant.line_id.in_(select(Line.id).where(Line.city_id == city.id)),
    )
    statements: dict[str, Select[Any]] = {
        "cities": select(City).where(City.id == city.id),
        "stations": select(Station).where(Station.city_id == city.id),
        "lines": select(Line).where(Line.city_id == city.id),
        "variants": select(RouteVariant).where(RouteVariant.id.in_(variants)),
        "stops": select(RouteStop).where(RouteStop.route_variant_id.in_(variants)),
        "edges": select(RouteEdge).where(RouteEdge.route_variant_id.in_(variants)),
        "aliases": select(StationAlias).where(
            StationAlias.station_id.in_(
                select(Station.id).where(Station.city_id == city.id)
            )
        ),
    }
    network: dict[str, list[dict[str, Any]]] = {}
    for name, model in TABLES.items():
        network[name] = [
            {
                key: value.hex() if isinstance(value, bytes) else value
                for key in _fields(model)
                for value in [getattr(row, key)]
            }
            for row in db.scalars(statements[name].order_by(model.__table__.c.id))
        ]
    content = _json_bytes(network)
    manifest = PackManifest(
        city_code=city.source_city_code,
        city_name=city.name_cn,
        network_sha256=hashlib.sha256(content).hexdigest(),
        source=PackSource(
            name=dataset.source_name,
            version=dataset.source_version,
            url=dataset.source_url,
            license=dataset.license,
            captured_at=dataset.captured_at,
            checksum=dataset.checksum,
            importer=dataset.importer_schema_version,
            attribution=attribution,
        ),
    )
    if dataset.importer_schema_version == "citypack-v1":
        saved = db.get(AppMeta, f"citypack.manifest.{dataset.id}")
        if saved is not None:
            manifest.source = PackManifest.model_validate_json(saved.value).source
    validate_network(network, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in (
            ("manifest.json", _json_bytes(manifest.model_dump())),
            ("network.json", content),
        ):
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return read_city_pack(output)[0]


def install_city_pack(db: Session, path: Path, expected_checksum: str) -> int:
    preview, network = read_city_pack(path)
    if preview.package_id != expected_checksum:
        raise CityPackError("城市包在预览后发生变化，请重新选择。")
    manifest = preview.manifest
    family = (
        "citypack:"
        + hashlib.sha256(manifest.source.name.encode()).hexdigest()[:8]
        + ":"
        + manifest.city_code
    )
    try:
        dataset = db.scalar(
            select(DatasetVersion).where(
                DatasetVersion.source_name == family,
                DatasetVersion.checksum == expected_checksum,
            )
        )
        if dataset is None:
            dataset = DatasetVersion(
                source_name=family,
                source_version=manifest.source.version,
                captured_at=manifest.source.captured_at,
                license=manifest.source.license,
                source_url=manifest.source.url,
                checksum=expected_checksum,
                importer_schema_version="citypack-v1",
                status="staging",
                total_cities=1,
                route_count=len(network["variants"]),
                stop_count=len(network["stops"]),
            )
            db.add(dataset)
            db.flush()
            maps: dict[str, dict[int, int]] = {}
            references = {
                "line_id": "lines",
                "station_id": "stations",
                "route_variant_id": "variants",
                "from_route_stop_id": "stops",
                "to_route_stop_id": "stops",
                "from_station_id": "stations",
                "to_station_id": "stations",
            }
            for name, model in TABLES.items():
                pending: list[tuple[int, Any]] = []
                for row in network[name]:
                    values = {
                        key: (
                            bytes.fromhex(value)
                            if key == "geometry_wkb"
                            else maps[references[key]][value]
                            if key in references
                            else value
                        )
                        for key, value in row.items()
                        if key != "id"
                    }
                    if "dataset_version_id" in model.__table__.columns:
                        values["dataset_version_id"] = dataset.id
                    if "city_id" in model.__table__.columns:
                        values["city_id"] = next(iter(maps["cities"].values()))
                    item = model(**values)
                    db.add(item)
                    pending.append((row["id"], item))
                db.flush()
                maps[name] = {old: item.id for old, item in pending}
        db.execute(
            update(DatasetVersion)
            .where(
                DatasetVersion.source_name == family,
                DatasetVersion.id != dataset.id,
                DatasetVersion.status == "ready",
            )
            .values(status="retired")
        )
        if dataset.status != "ready":
            dataset.imported_at = datetime.now(UTC)
        dataset.status = "ready"
        dataset.completed_at = datetime.now(UTC)
        dataset.processed_cities = 1
        dataset.ready_lines = sum(row["status"] == "ready" for row in network["lines"])
        dataset.blocked_lines = sum(
            row["status"] == "blocked" for row in network["lines"]
        )
        saved = db.get(AppMeta, f"citypack.manifest.{dataset.id}")
        if saved is None:
            db.add(
                AppMeta(
                    key=f"citypack.manifest.{dataset.id}",
                    value=manifest.model_dump_json(),
                )
            )
        else:
            saved.value = manifest.model_dump_json()
        db.commit()
        return dataset.id
    except Exception:
        db.rollback()
        raise
