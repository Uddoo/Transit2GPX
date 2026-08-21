from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz.fuzz import WRatio
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import RailDatasetVersion, RailStation, RailStationAlias
from app.matching.names import normalize_station_name, pinyin_keys


@dataclass(frozen=True, slots=True)
class RailStationMatch:
    station: RailStation
    score: float
    match_method: str


def _active_dataset(
    db: Session, rail_dataset_version_id: int | None
) -> RailDatasetVersion | None:
    statement = select(RailDatasetVersion).where(RailDatasetVersion.status == "ready")
    if rail_dataset_version_id is not None:
        statement = statement.where(RailDatasetVersion.id == rail_dataset_version_id)
    return db.scalar(
        statement.order_by(
            RailDatasetVersion.imported_at.desc(), RailDatasetVersion.id.desc()
        )
    )


def _aliases_by_station(
    db: Session, station_ids: Sequence[int]
) -> dict[int, list[str]]:
    aliases: dict[int, list[str]] = {}
    if not station_ids:
        return aliases
    for station_id, alias in db.execute(
        select(RailStationAlias.station_id, RailStationAlias.normalized_alias).where(
            RailStationAlias.station_id.in_(station_ids)
        )
    ):
        aliases.setdefault(station_id, []).append(alias)
    return aliases


def _station_keys(
    station: RailStation, aliases: Sequence[str]
) -> list[tuple[str, str]]:
    return [
        (key, method)
        for key, method in (
            (station.normalized_name, "name"),
            (normalize_station_name(station.name_cn), "name"),
            (normalize_station_name(station.name_en or ""), "name_en"),
            (station.pinyin_full or "", "pinyin"),
            (station.pinyin_initials or "", "pinyin_initials"),
            (normalize_station_name(station.station_code or ""), "station_code"),
            *((normalize_station_name(alias), "alias") for alias in aliases),
        )
        if key
    ]


def _score(query: str, keys: Sequence[tuple[str, str]]) -> tuple[float, str]:
    best = (0.0, "fuzzy")
    for key, method in keys:
        if query == key:
            candidate = (100.0, method)
        elif key.startswith(query):
            candidate = (96.0, method)
        elif query in key:
            candidate = (92.0, method)
        else:
            candidate = (float(WRatio(query, key)), f"{method}_fuzzy")
        if candidate[0] > best[0]:
            best = candidate
    return best


def search_ready_rail_stations(
    db: Session,
    *,
    value: str,
    rail_dataset_version_id: int | None = None,
    province_name: str | None = None,
    city_name: str | None = None,
    limit: int = 30,
) -> list[RailStationMatch]:
    query_key = normalize_station_name(value)
    query_pinyin, _ = pinyin_keys(value)
    query = query_key or query_pinyin
    if not query:
        return []
    dataset = _active_dataset(db, rail_dataset_version_id)
    if dataset is None:
        return []
    alias_station_ids = select(RailStationAlias.station_id).where(
        RailStationAlias.normalized_alias.contains(query)
    )
    statement = select(RailStation).where(
        RailStation.rail_dataset_version_id == dataset.id,
        RailStation.match_status == "ready",
    )
    if province_name:
        statement = statement.where(RailStation.province_name == province_name)
    if city_name:
        statement = statement.where(RailStation.city_name == city_name)
    filtered_statement = statement.where(
        or_(
            RailStation.normalized_name.contains(query),
            RailStation.pinyin_full.contains(query),
            RailStation.pinyin_initials.contains(query),
            func.lower(RailStation.station_code) == query.casefold(),
            RailStation.id.in_(alias_station_ids),
        )
    )
    stations = list(
        db.scalars(filtered_statement.order_by(RailStation.name_cn).limit(500)).all()
    )
    if not stations:
        stations = list(
            db.scalars(statement.order_by(RailStation.name_cn).limit(5000)).all()
        )
    aliases = _aliases_by_station(db, [station.id for station in stations])
    threshold = get_settings().station_search_min_score
    matches: list[RailStationMatch] = []
    for station in stations:
        score, method = _score(
            query, _station_keys(station, aliases.get(station.id, ()))
        )
        if score >= threshold:
            matches.append(
                RailStationMatch(
                    station=station,
                    score=score,
                    match_method=method,
                )
            )
    matches.sort(
        key=lambda match: (-match.score, match.station.name_cn, match.station.id)
    )
    return matches[:limit]
