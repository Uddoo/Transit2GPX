from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz.fuzz import WRatio
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    City,
    DatasetVersion,
    RouteStop,
    RouteVariant,
    Station,
    StationAlias,
)
from app.matching.names import normalize_station_name, pinyin_keys
from app.matching.search import fts_prefix_expression


def stations_for_line(db: Session, line_id: int) -> list[Station]:
    first_sequence = (
        select(
            RouteStop.station_id,
            func.min(RouteStop.source_sequence).label("first_sequence"),
        )
        .join(RouteVariant, RouteVariant.id == RouteStop.route_variant_id)
        .where(
            RouteVariant.line_id == line_id,
            RouteVariant.quality_status == "ready",
        )
        .group_by(RouteStop.station_id)
        .subquery()
    )
    return list(
        db.scalars(
            select(Station)
            .join(first_sequence, first_sequence.c.station_id == Station.id)
            .order_by(first_sequence.c.first_sequence, Station.id)
        ).all()
    )


def _aliases_by_station(
    db: Session, station_ids: Sequence[int]
) -> dict[int, list[str]]:
    aliases: dict[int, list[str]] = {}
    if not station_ids:
        return aliases
    for station_id, alias in db.execute(
        select(StationAlias.station_id, StationAlias.normalized_alias).where(
            StationAlias.station_id.in_(station_ids)
        )
    ):
        aliases.setdefault(station_id, []).append(alias)
    return aliases


def _station_keys(station: Station, aliases: Sequence[str]) -> set[str]:
    return {
        key
        for key in (
            station.normalized_name,
            normalize_station_name(station.name_cn),
            normalize_station_name(station.name_en or ""),
            station.pinyin_full or "",
            station.pinyin_initials or "",
            *(normalize_station_name(alias) for alias in aliases),
        )
        if key
    }


def exact_line_station_matches(
    db: Session, *, line_id: int, value: str
) -> list[Station]:
    query_key = normalize_station_name(value)
    if not query_key:
        return []
    stations = stations_for_line(db, line_id)
    aliases = _aliases_by_station(db, [station.id for station in stations])
    return [
        station
        for station in stations
        if query_key in _station_keys(station, aliases.get(station.id, ()))
    ]


def search_ready_stations(
    db: Session,
    *,
    city_id: int,
    value: str,
    line_id: int | None,
    limit: int,
) -> list[Station]:
    city = db.scalar(
        select(City)
        .join(DatasetVersion)
        .where(
            City.id == city_id,
            City.status == "ready",
            DatasetVersion.status == "ready",
        )
    )
    if city is None:
        return []

    eligible = (
        stations_for_line(db, line_id)
        if line_id is not None
        else list(db.scalars(select(Station).where(Station.city_id == city_id)).all())
    )
    eligible_by_id = {station.id: station for station in eligible}
    ranked: list[Station] = []
    expression = fts_prefix_expression(value)
    if expression:
        rows = db.execute(
            text(
                "SELECT station_id FROM station_fts "
                "WHERE station_fts MATCH :query AND city_id=:city_id "
                "ORDER BY bm25(station_fts), station_id LIMIT :candidate_limit"
            ),
            {
                "query": expression,
                "city_id": city_id,
                "candidate_limit": max(limit * 5, 50),
            },
        ).all()
        ranked = [
            eligible_by_id[station_id]
            for (station_id,) in rows
            if station_id in eligible_by_id
        ][:limit]

    if len(ranked) >= limit:
        return ranked
    ranked_ids = {station.id for station in ranked}
    aliases = _aliases_by_station(db, list(eligible_by_id))
    query_key = normalize_station_name(value)
    query_pinyin, _ = pinyin_keys(value)
    fuzzy_query = query_key or query_pinyin
    if not fuzzy_query:
        return ranked
    scored: list[tuple[float, str, int, Station]] = []
    threshold = get_settings().station_search_min_score
    for station in eligible:
        if station.id in ranked_ids:
            continue
        score = max(
            WRatio(fuzzy_query, key)
            for key in _station_keys(station, aliases.get(station.id, ()))
        )
        if score >= threshold:
            scored.append((score, station.name_cn, station.id, station))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    ranked.extend(item[3] for item in scored[: limit - len(ranked)])
    return ranked
