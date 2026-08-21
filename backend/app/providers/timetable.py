from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.providers.contracts import RailTravelFacts
from app.rail.resolver import RailTrainType


@dataclass(frozen=True, slots=True)
class UserFactsTimetableProvider:
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
    ) -> RailTravelFacts:
        normalized_train_no = train_no.strip().upper() if train_no else None
        normalized_route_hint = route_hint.strip() if route_hint else None
        return RailTravelFacts(
            travel_date=travel_date,
            train_no=normalized_train_no or None,
            train_type=train_type,
            start_station_id=start_station_id,
            end_station_id=end_station_id,
            via_station_ids=tuple(via_station_ids),
            route_hint=normalized_route_hint or None,
            timetable_provider=self.name,
        )


MANUAL_TIMETABLE_PROVIDER = UserFactsTimetableProvider(name="manual")
CSV_TIMETABLE_PROVIDER = UserFactsTimetableProvider(name="csv")
