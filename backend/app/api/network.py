from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.active_cities import current_city_ids
from app.db.base import AppMeta
from app.db.models import City, DatasetVersion, Line, RouteVariant, Station
from app.db.session import get_db
from app.importers.city_pack import PackManifest
from app.matching.stations import search_ready_stations, stations_for_line

router = APIRouter(tags=["network"])


class CityResponse(BaseModel):
    id: int
    name_cn: str
    name_en: str | None
    center: tuple[float, float]
    bbox: tuple[float, float, float, float]
    city_code: str = ""
    source_name: str | None = None
    source_version: str | None = None
    captured_at: str | None = None
    license: str | None = None
    checksum: str | None = None
    station_count: int = 0
    direction_count: int = 0


class LineResponse(BaseModel):
    id: int
    city_id: int
    name_cn: str
    name_en: str | None
    display_color: str | None


class StationResponse(BaseModel):
    id: int
    city_id: int
    name_cn: str
    name_en: str | None
    lon: float
    lat: float


def _station_response(station: Station) -> StationResponse:
    return StationResponse(
        id=station.id,
        city_id=station.city_id,
        name_cn=station.name_cn,
        name_en=station.name_en,
        lon=station.lon,
        lat=station.lat,
    )


@router.get("/cities", response_model=list[CityResponse])
def list_cities(db: Session = Depends(get_db)) -> list[CityResponse]:
    rows = db.execute(
        select(City, DatasetVersion)
        .join(DatasetVersion)
        .where(City.id.in_(current_city_ids()), DatasetVersion.status == "ready")
        .order_by(City.name_cn, City.id)
    ).all()
    city_ids = [city.id for city, _ in rows]
    station_counts = {
        key: count
        for key, count in db.execute(
            select(Station.city_id, func.count())
            .where(Station.city_id.in_(city_ids))
            .group_by(Station.city_id)
        ).all()
    }
    direction_counts = {
        key: count
        for key, count in db.execute(
            select(Line.city_id, func.count(RouteVariant.id))
            .join(RouteVariant)
            .where(Line.city_id.in_(city_ids), RouteVariant.quality_status == "ready")
            .group_by(Line.city_id)
        ).all()
    }
    metadata = {
        row.key: row.value
        for row in db.scalars(
            select(AppMeta).where(
                AppMeta.key.in_(
                    [f"citypack.manifest.{dataset.id}" for _, dataset in rows]
                )
            )
        )
    }
    sources = {}
    for _, dataset in rows:
        if saved := metadata.get(f"citypack.manifest.{dataset.id}"):
            with suppress(ValueError):
                sources[dataset.id] = PackManifest.model_validate_json(saved).source
    return [
        CityResponse(
            id=city.id,
            name_cn=city.name_cn,
            name_en=city.name_en,
            center=(city.center_lon, city.center_lat),
            bbox=(city.min_lon, city.min_lat, city.max_lon, city.max_lat),
            city_code=city.source_city_code,
            source_name=sources[dataset.id].name
            if dataset.id in sources
            else dataset.source_name,
            source_version=sources[dataset.id].version
            if dataset.id in sources
            else dataset.source_version,
            captured_at=dataset.captured_at,
            license=dataset.license,
            checksum=dataset.checksum,
            station_count=station_counts.get(city.id, 0),
            direction_count=direction_counts.get(city.id, 0),
        )
        for city, dataset in rows
    ]


@router.get("/cities/{city_id}/lines", response_model=list[LineResponse])
def list_lines(city_id: int, db: Session = Depends(get_db)) -> list[LineResponse]:
    lines = db.scalars(
        select(Line)
        .join(City)
        .join(DatasetVersion)
        .where(
            Line.city_id == city_id,
            Line.status == "ready",
            City.id.in_(current_city_ids()),
            DatasetVersion.status == "ready",
        )
        .order_by(Line.sort_order, Line.name_cn, Line.id)
    ).all()
    return [
        LineResponse(
            id=line.id,
            city_id=line.city_id,
            name_cn=line.name_cn,
            name_en=line.name_en,
            display_color=line.display_color,
        )
        for line in lines
    ]


@router.get("/cities/{city_id}/stations", response_model=list[StationResponse])
def list_city_stations(
    city_id: int, db: Session = Depends(get_db)
) -> list[StationResponse]:
    stations = db.scalars(
        select(Station)
        .join(City, City.id == Station.city_id)
        .join(DatasetVersion, DatasetVersion.id == City.dataset_version_id)
        .where(
            Station.city_id == city_id,
            City.id.in_(current_city_ids()),
            DatasetVersion.status == "ready",
        )
        .order_by(Station.name_cn, Station.id)
    ).all()
    return [_station_response(station) for station in stations]


@router.get("/lines/{line_id}/stations", response_model=list[StationResponse])
def list_line_stations(
    line_id: int, db: Session = Depends(get_db)
) -> list[StationResponse]:
    stations = stations_for_line(db, line_id)
    return [_station_response(station) for station in stations]


@router.get("/stations/search", response_model=list[StationResponse])
def search_stations(
    q: str = Query(min_length=1, max_length=120),
    city_id: int = Query(gt=0),
    line_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[StationResponse]:
    stations = search_ready_stations(
        db, city_id=city_id, value=q, line_id=line_id, limit=limit
    )
    return [_station_response(station) for station in stations]
