from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased, defer

from app.db.models import (
    City,
    Journey,
    JourneyLeg,
    JourneyLegEdge,
    Line,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RailJourneyLegDetail,
    RailJourneyStop,
    RailStation,
    RouteEdge,
    Station,
)


@dataclass(frozen=True, slots=True)
class JourneyQueryContext:
    legs_by_journey: dict[int, list[JourneyLeg]]
    cities: dict[int, City]
    lines: dict[int, Line]
    stations: dict[int, Station]
    metro_edges_by_leg: dict[int, list[tuple[JourneyLegEdge, float]]]
    rail_details: dict[int, RailJourneyLegDetail]
    rail_stations_by_leg: dict[int, list[RailStation]]
    rail_snapshots_by_leg: dict[int, list[RailJourneyEdgeSnapshot]]
    rail_datasets: dict[int, RailDatasetVersion]


def select_journey_page(
    db: Session,
    *,
    city_id: int | None,
    line_id: int | None,
    query: str | None,
    limit: int,
    offset: int,
    traveled_from: date | None = None,
    traveled_to: date | None = None,
) -> tuple[list[Journey], int]:
    statement = select(Journey).order_by(Journey.traveled_at.desc(), Journey.id.desc())
    if city_id is not None or line_id is not None:
        statement = statement.join(JourneyLeg)
        if city_id is not None:
            statement = statement.where(JourneyLeg.city_id == city_id)
        if line_id is not None:
            statement = statement.where(JourneyLeg.line_id == line_id)
        statement = statement.distinct()
    if traveled_from is not None:
        statement = statement.where(Journey.traveled_at >= traveled_from)
    if traveled_to is not None:
        statement = statement.where(Journey.traveled_at <= traveled_to)
    if query and query.strip():
        # Literal contains matching; search station/line/train names across all pages.
        pattern = (
            "%"
            + query.strip().replace("/", "//").replace("%", "/%").replace("_", "/_")
            + "%"
        )
        start_station = aliased(Station)
        end_station = aliased(Station)
        matching_legs = (
            select(JourneyLeg.journey_id)
            .outerjoin(City, City.id == JourneyLeg.city_id)
            .outerjoin(Line, Line.id == JourneyLeg.line_id)
            .outerjoin(start_station, start_station.id == JourneyLeg.start_station_id)
            .outerjoin(end_station, end_station.id == JourneyLeg.end_station_id)
            .outerjoin(
                RailJourneyLegDetail,
                RailJourneyLegDetail.journey_leg_id == JourneyLeg.id,
            )
            .outerjoin(RailJourneyStop, RailJourneyStop.journey_leg_id == JourneyLeg.id)
            .outerjoin(RailStation, RailStation.id == RailJourneyStop.station_id)
            .where(
                or_(
                    City.name_cn.ilike(pattern, escape="/"),
                    Line.name_cn.ilike(pattern, escape="/"),
                    start_station.name_cn.ilike(pattern, escape="/"),
                    end_station.name_cn.ilike(pattern, escape="/"),
                    RailStation.name_cn.ilike(pattern, escape="/"),
                    RailJourneyLegDetail.train_no.ilike(pattern, escape="/"),
                    RailJourneyLegDetail.train_type.ilike(pattern, escape="/"),
                )
            )
        )
        statement = statement.where(
            or_(
                Journey.journey_code.ilike(pattern, escape="/"),
                Journey.note.ilike(pattern, escape="/"),
                Journey.id.in_(matching_legs),
            )
        )
    journeys = list(db.scalars(statement.offset(offset).limit(limit)).all())
    total = int(
        db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    return journeys, total


def load_journey_context(
    db: Session, journeys: Sequence[Journey]
) -> JourneyQueryContext:
    journey_ids = [journey.id for journey in journeys]
    if not journey_ids:
        return JourneyQueryContext({}, {}, {}, {}, {}, {}, {}, {}, {})

    legs = list(
        db.scalars(
            select(JourneyLeg)
            .where(JourneyLeg.journey_id.in_(journey_ids))
            .order_by(JourneyLeg.journey_id, JourneyLeg.leg_no)
        ).all()
    )
    legs_by_journey: defaultdict[int, list[JourneyLeg]] = defaultdict(list)
    for leg in legs:
        legs_by_journey[leg.journey_id].append(leg)

    metro_legs = [leg for leg in legs if leg.transport_mode == "metro"]
    rail_legs = [leg for leg in legs if leg.transport_mode == "rail"]
    city_ids = {leg.city_id for leg in metro_legs if leg.city_id is not None}
    line_ids = {leg.line_id for leg in metro_legs if leg.line_id is not None}
    station_ids = {
        station_id
        for leg in metro_legs
        for station_id in (leg.start_station_id, leg.end_station_id)
        if station_id is not None
    }
    cities = (
        {
            item.id: item
            for item in db.scalars(select(City).where(City.id.in_(city_ids)))
        }
        if city_ids
        else {}
    )
    lines = (
        {
            item.id: item
            for item in db.scalars(select(Line).where(Line.id.in_(line_ids)))
        }
        if line_ids
        else {}
    )
    stations = (
        {
            item.id: item
            for item in db.scalars(select(Station).where(Station.id.in_(station_ids)))
        }
        if station_ids
        else {}
    )

    metro_leg_ids = [leg.id for leg in metro_legs]
    metro_edges_by_leg: defaultdict[int, list[tuple[JourneyLegEdge, float]]] = (
        defaultdict(list)
    )
    if metro_leg_ids:
        edge_rows = db.execute(
            select(JourneyLegEdge, RouteEdge.distance_m)
            .join(RouteEdge, RouteEdge.id == JourneyLegEdge.route_edge_id)
            .where(JourneyLegEdge.journey_leg_id.in_(metro_leg_ids))
            .order_by(JourneyLegEdge.journey_leg_id, JourneyLegEdge.order_no)
        ).all()
        for edge, distance_m in edge_rows:
            metro_edges_by_leg[edge.journey_leg_id].append((edge, distance_m))

    rail_leg_ids = [leg.id for leg in rail_legs]
    rail_details: dict[int, RailJourneyLegDetail] = {}
    rail_stations_by_leg: defaultdict[int, list[RailStation]] = defaultdict(list)
    rail_snapshots_by_leg: defaultdict[int, list[RailJourneyEdgeSnapshot]] = (
        defaultdict(list)
    )
    if rail_leg_ids:
        rail_details = {
            item.journey_leg_id: item
            for item in db.scalars(
                select(RailJourneyLegDetail).where(
                    RailJourneyLegDetail.journey_leg_id.in_(rail_leg_ids)
                )
            )
        }
        stop_rows = db.execute(
            select(RailJourneyStop, RailStation)
            .join(RailStation, RailStation.id == RailJourneyStop.station_id)
            .where(RailJourneyStop.journey_leg_id.in_(rail_leg_ids))
            .order_by(RailJourneyStop.journey_leg_id, RailJourneyStop.stop_sequence)
        ).all()
        for stop, station in stop_rows:
            rail_stations_by_leg[stop.journey_leg_id].append(station)
        snapshots = db.scalars(
            select(RailJourneyEdgeSnapshot)
            .options(defer(RailJourneyEdgeSnapshot.geometry_wkb))
            .where(RailJourneyEdgeSnapshot.journey_leg_id.in_(rail_leg_ids))
            .order_by(
                RailJourneyEdgeSnapshot.journey_leg_id,
                RailJourneyEdgeSnapshot.order_no,
            )
        ).all()
        for snapshot in snapshots:
            rail_snapshots_by_leg[snapshot.journey_leg_id].append(snapshot)

    rail_dataset_ids = {
        snapshot.rail_dataset_version_id
        for snapshots in rail_snapshots_by_leg.values()
        for snapshot in snapshots
    }
    rail_datasets = (
        {
            item.id: item
            for item in db.scalars(
                select(RailDatasetVersion).where(
                    RailDatasetVersion.id.in_(rail_dataset_ids)
                )
            )
        }
        if rail_dataset_ids
        else {}
    )
    return JourneyQueryContext(
        legs_by_journey=dict(legs_by_journey),
        cities=cities,
        lines=lines,
        stations=stations,
        metro_edges_by_leg=dict(metro_edges_by_leg),
        rail_details=rail_details,
        rail_stations_by_leg=dict(rail_stations_by_leg),
        rail_snapshots_by_leg=dict(rail_snapshots_by_leg),
        rail_datasets=rail_datasets,
    )
