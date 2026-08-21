from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from sqlalchemy.orm import Session

from app.rail.resolver import RailPathResolution, RailTrainType
from app.routing.resolver import MultiLineResolution, Resolution


@dataclass(frozen=True, slots=True)
class RailTravelFacts:
    travel_date: date
    train_no: str | None
    train_type: RailTrainType
    start_station_id: int
    end_station_id: int
    via_station_ids: tuple[int, ...]
    route_hint: str | None
    timetable_provider: str


class TimetableProvider(Protocol):
    name: str

    def create_facts(
        self,
        *,
        travel_date: date,
        train_no: str | None,
        train_type: RailTrainType,
        start_station_id: int,
        end_station_id: int,
        via_station_ids: list[int] | tuple[int, ...],
        route_hint: str | None,
    ) -> RailTravelFacts: ...


class MetroProvider(Protocol):
    name: str

    def resolve_line(
        self,
        db: Session,
        *,
        line_id: int,
        start_station_id: int,
        end_station_id: int,
        direction: str,
        via_station_ids: list[int],
    ) -> Resolution: ...

    def resolve_city(
        self,
        db: Session,
        *,
        city_id: int,
        start_station_id: int,
        end_station_id: int,
        via_station_ids: list[int],
    ) -> MultiLineResolution: ...


class RailwayProvider(Protocol):
    name: str

    def resolve(self, db: Session, facts: RailTravelFacts) -> RailPathResolution: ...
