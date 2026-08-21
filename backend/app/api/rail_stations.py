from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.matching.rail_stations import search_ready_rail_stations

router = APIRouter(prefix="/rail/stations", tags=["rail stations"])


class RailStationResponse(BaseModel):
    id: int
    rail_dataset_version_id: int
    osm_type: str
    osm_id: int
    name_cn: str
    name_en: str | None
    station_code: str | None
    city_name: str | None
    province_name: str | None
    lon: float
    lat: float
    match_score: float
    match_method: str


@router.get("/search", response_model=list[RailStationResponse])
def search_rail_stations(
    q: str = Query(min_length=1, max_length=120),
    rail_dataset_version_id: int | None = Query(default=None, gt=0),
    province_name: str | None = Query(default=None, max_length=160),
    city_name: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[RailStationResponse]:
    matches = search_ready_rail_stations(
        db,
        value=q,
        rail_dataset_version_id=rail_dataset_version_id,
        province_name=province_name,
        city_name=city_name,
        limit=limit,
    )
    return [
        RailStationResponse(
            id=match.station.id,
            rail_dataset_version_id=match.station.rail_dataset_version_id,
            osm_type=match.station.osm_type,
            osm_id=match.station.osm_id,
            name_cn=match.station.name_cn,
            name_en=match.station.name_en,
            station_code=match.station.station_code,
            city_name=match.station.city_name,
            province_name=match.station.province_name,
            lon=match.station.lon,
            lat=match.station.lat,
            match_score=match.score,
            match_method=match.match_method,
        )
        for match in matches
    ]
