from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.providers.contracts import RailTravelFacts
from app.rail.resolver import RailPathResolution, resolve_rail_path
from app.routing.resolver import (
    MultiLineResolution,
    Resolution,
    resolve_city_path,
    resolve_line_path,
)


@dataclass(frozen=True, slots=True)
class CPTONDMetroProvider:
    name: str = "cptond"

    def resolve_line(
        self,
        db: Session,
        *,
        line_id: int,
        start_station_id: int,
        end_station_id: int,
        direction: str,
        via_station_ids: list[int],
    ) -> Resolution:
        return resolve_line_path(
            db,
            line_id=line_id,
            start_station_id=start_station_id,
            end_station_id=end_station_id,
            direction=direction,
            via_station_ids=via_station_ids,
        )

    def resolve_city(
        self,
        db: Session,
        *,
        city_id: int,
        start_station_id: int,
        end_station_id: int,
        via_station_ids: list[int],
    ) -> MultiLineResolution:
        return resolve_city_path(
            db,
            city_id=city_id,
            start_station_id=start_station_id,
            end_station_id=end_station_id,
            via_station_ids=via_station_ids,
        )


@dataclass(frozen=True, slots=True)
class OSMRailwayProvider:
    name: str = "openstreetmap-openrailrouting"

    def resolve(self, db: Session, facts: RailTravelFacts) -> RailPathResolution:
        return resolve_rail_path(
            db,
            travel_date=facts.travel_date,
            train_no=facts.train_no,
            train_type=facts.train_type,
            start_station_id=facts.start_station_id,
            end_station_id=facts.end_station_id,
            via_station_ids=list(facts.via_station_ids),
            route_hint=facts.route_hint,
        )


METRO_PROVIDER = CPTONDMetroProvider()
RAILWAY_PROVIDER = OSMRailwayProvider()
