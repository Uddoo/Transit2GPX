from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from shapely import wkb
from shapely.geometry import mapping
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.db.models import City, DatasetVersion, Line, RouteStop, RouteVariant, Station
from app.db.session import get_db
from app.services.spatial_queries import (
    route_variant_ids_in_bbox,
    station_ids_in_bbox,
)

router = APIRouter(prefix="/cities", tags=["map"])


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict[str, Any]] = Field(default_factory=list)


class CityMapResponse(BaseModel):
    city_id: int
    dataset_version_id: int
    bbox: tuple[float, float, float, float]
    lines: FeatureCollection
    stations: FeatureCollection


def _parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    try:
        parsed = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise APIError(
            status_code=422,
            code="invalid_bbox",
            message="bbox 必须包含四个 WGS-84 数值",
        ) from error
    if len(parsed) != 4:
        raise APIError(
            status_code=422,
            code="invalid_bbox",
            message="bbox 必须是 min_lon,min_lat,max_lon,max_lat",
        )
    min_lon, min_lat, max_lon, max_lat = parsed
    if not -180 <= min_lon < max_lon <= 180 or not -90 <= min_lat < max_lat <= 90:
        raise APIError(
            status_code=422,
            code="invalid_bbox",
            message="bbox 坐标范围或顺序无效",
        )
    return min_lon, min_lat, max_lon, max_lat


def _ready_city(db: Session, city_id: int) -> City:
    city = db.scalar(
        select(City)
        .join(DatasetVersion)
        .where(
            City.id == city_id,
            City.status == "ready",
            DatasetVersion.status == "ready",
        )
    )
    if city is not None:
        return city
    has_dataset = db.scalar(
        select(func.count())
        .select_from(DatasetVersion)
        .where(DatasetVersion.status == "ready")
    )
    if not has_dataset:
        raise APIError(
            status_code=409,
            code="dataset_not_ready",
            message="尚未导入可用的真实地铁线路数据",
            details={"city_id": city_id},
        )
    raise APIError(
        status_code=404,
        code="city_not_found",
        message="没有找到可用城市",
        details={"city_id": city_id},
    )


def _station_query(city_id: int, line_id: int | None) -> Select[tuple[Station]]:
    query = select(Station).where(Station.city_id == city_id)
    if line_id is None:
        return query
    return (
        query.join(RouteStop, RouteStop.station_id == Station.id)
        .join(RouteVariant, RouteVariant.id == RouteStop.route_variant_id)
        .where(RouteVariant.line_id == line_id)
        .distinct()
    )


@router.get("/{city_id}/map", response_model=CityMapResponse)
def city_map(
    city_id: int,
    line_id: int | None = None,
    bbox: str | None = Query(
        default=None,
        description="WGS-84 min_lon,min_lat,max_lon,max_lat",
    ),
    db: Session = Depends(get_db),
) -> CityMapResponse:
    """Return imported line and station GeoJSON for one city viewport."""

    city = _ready_city(db, city_id)
    selected_bbox = _parse_bbox(bbox) or (
        city.min_lon,
        city.min_lat,
        city.max_lon,
        city.max_lat,
    )
    min_lon, min_lat, max_lon, max_lat = selected_bbox

    visible_variants = route_variant_ids_in_bbox(selected_bbox)
    line_query = (
        select(RouteVariant, Line)
        .join(Line, Line.id == RouteVariant.line_id)
        .join(visible_variants, visible_variants.c.id == RouteVariant.id)
        .where(
            Line.city_id == city.id,
            Line.status == "ready",
            RouteVariant.quality_status == "ready",
        )
        .order_by(Line.sort_order, Line.name_cn, RouteVariant.id)
    )
    if line_id is not None:
        line_query = line_query.where(Line.id == line_id)

    line_features: list[dict[str, Any]] = []
    for variant, line in db.execute(line_query).all():
        geometry = wkb.loads(variant.geometry_wkb)
        geom_min_lon, geom_min_lat, geom_max_lon, geom_max_lat = geometry.bounds
        if (
            geom_max_lon < min_lon
            or geom_min_lon > max_lon
            or geom_max_lat < min_lat
            or geom_min_lat > max_lat
        ):
            continue
        line_features.append(
            {
                "type": "Feature",
                "id": f"variant-{variant.id}",
                "geometry": mapping(geometry),
                "properties": {
                    "kind": "line",
                    "line_id": line.id,
                    "route_variant_id": variant.id,
                    "name_cn": line.name_cn,
                    "name_en": line.name_en,
                    "direction_name": variant.direction_name,
                    "display_color": line.display_color,
                    "quality_status": variant.quality_status,
                },
            }
        )

    visible_stations = station_ids_in_bbox(selected_bbox)
    station_query = _station_query(city.id, line_id).join(
        visible_stations, visible_stations.c.id == Station.id
    )
    stations = db.scalars(station_query.order_by(Station.name_cn, Station.id)).all()
    station_features = [
        {
            "type": "Feature",
            "id": f"station-{station.id}",
            "geometry": {"type": "Point", "coordinates": [station.lon, station.lat]},
            "properties": {
                "kind": "station",
                "station_id": station.id,
                "name_cn": station.name_cn,
                "name_en": station.name_en,
            },
        }
        for station in stations
    ]

    return CityMapResponse(
        city_id=city.id,
        dataset_version_id=city.dataset_version_id,
        bbox=selected_bbox,
        lines=FeatureCollection(features=line_features),
        stations=FeatureCollection(features=station_features),
    )
