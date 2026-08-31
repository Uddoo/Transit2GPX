from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from hashlib import sha256
from pathlib import Path

import pytest
from factories import seed_linear_network
from fastapi.testclient import TestClient
from shapely.geometry import LineString
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Journey,
    JourneyLeg,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RailJourneyLegDetail,
    RailJourneyStop,
    RailStation,
    StationAlias,
)
from app.matching.names import normalize_station_name


def test_first_run_creates_complete_domain_schema(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200

    from app.core.config import get_settings

    database_path = Path(
        get_settings().resolved_database_url.removeprefix("sqlite:///")
    )
    with closing(sqlite3.connect(database_path)) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        trigger_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }

    assert {
        "dataset_version",
        "city",
        "line",
        "route_variant",
        "station",
        "station_alias",
        "route_stop",
        "route_edge",
        "journey",
        "journey_leg",
        "journey_leg_edge",
        "rail_dataset_version",
        "rail_station",
        "rail_station_alias",
        "rail_journey_leg_detail",
        "rail_journey_stop",
        "rail_journey_edge_snapshot",
        "app_task",
        "import_batch",
        "import_row",
    } <= table_names
    assert {
        "station_fts",
        "rail_station_fts",
        "station_spatial",
        "route_edge_spatial",
    } <= table_names
    assert {
        "station_fts_insert",
        "rail_station_fts_insert",
        "rail_station_alias_fts_insert",
        "station_spatial_insert",
        "route_edge_spatial_insert",
    } <= trigger_names


def test_city_map_returns_seeded_geojson(client: TestClient, db: Session) -> None:
    network = seed_linear_network(db)

    from app.db.session import engine

    statements: list[str] = []

    def capture_statement(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,  # type: ignore[no-untyped-def]
    ) -> None:
        del connection, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = client.get(
            f"/api/v1/cities/{network.city_id}/map?line_id={network.line_id}"
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert response.status_code == 200
    assert any("route_edge_spatial" in statement for statement in statements)
    assert any("station_spatial" in statement for statement in statements)
    body = response.json()
    assert body["city_id"] == network.city_id
    assert body["dataset_version_id"] == network.dataset_id
    assert body["bbox"] == [121.4, 31.18, 121.5, 31.22]
    assert len(body["lines"]["features"]) == 1
    assert body["lines"]["features"][0]["properties"]["name_cn"] == "测试线"
    assert {
        feature["properties"]["name_cn"] for feature in body["stations"]["features"]
    } == {"甲站", "乙站", "丙站"}

    invalid = client.get(
        f"/api/v1/cities/{network.city_id}/map?bbox=121.5,31.18,121.4,31.22"
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_bbox"


def test_search_and_spatial_indexes_follow_domain_rows(
    client: TestClient, db: Session
) -> None:
    del client
    network = seed_linear_network(db)
    station_hits = db.execute(
        text(
            "SELECT station_id FROM station_fts "
            "WHERE station_fts MATCH :query AND city_id=:city_id"
        ),
        {"query": "jiazhan", "city_id": network.city_id},
    ).all()
    spatial_hits = db.execute(
        text(
            "SELECT id FROM station_spatial "
            "WHERE min_lon >= 121.39 AND max_lon <= 121.51"
        )
    ).all()
    assert station_hits == [(network.station_ids[0],)]
    assert {row[0] for row in spatial_hits} == set(network.station_ids)


def test_station_api_uses_fts_aliases_and_route_order(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    db.add(
        StationAlias(
            station_id=network.station_ids[0],
            alias="彩虹桥",
            normalized_alias=normalize_station_name("彩虹桥"),
            language="zh",
            source="test",
        )
    )
    db.commit()

    listing = client.get(f"/api/v1/lines/{network.line_id}/stations")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == list(network.station_ids)

    alias_search = client.get(
        "/api/v1/stations/search",
        params={
            "q": "彩虹",
            "city_id": network.city_id,
            "line_id": network.line_id,
        },
    )
    assert alias_search.status_code == 200
    assert [item["id"] for item in alias_search.json()] == [network.station_ids[0]]

    pinyin_search = client.get(
        "/api/v1/stations/search",
        params={"q": "yizhan", "city_id": network.city_id},
    )
    assert pinyin_search.status_code == 200
    assert pinyin_search.json()[0]["id"] == network.station_ids[1]

    unsafe_query = client.get(
        "/api/v1/stations/search",
        params={"q": '"', "city_id": network.city_id},
    )
    assert unsafe_query.status_code == 200
    assert unsafe_query.json() == []


def test_rail_leg_uses_shared_journey_and_immutable_snapshot(db: Session) -> None:
    dataset = RailDatasetVersion(
        source_name="OpenStreetMap/Geofabrik",
        source_url="https://download.geofabrik.de/asia/china.html",
        source_timestamp="2026-08-20",
        pbf_checksum="b" * 64,
        extract_region="test",
        graph_version="test-rail-20260820",
        profile_version="2026-08-21-r0.1",
        openrailrouting_version="c8d4ef1",
        graphhopper_version="11.0-osm-reader-callbacks",
        license="ODbL-1.0",
        status="ready",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.flush()
    stations: list[RailStation] = []
    for osm_id, name, lon in (
        (1001, "上海虹桥", 121.327),
        (1002, "杭州东", 120.212),
    ):
        station = RailStation(
            rail_dataset_version_id=dataset.id,
            osm_type="node",
            osm_id=osm_id,
            name_cn=name,
            name_en=None,
            normalized_name=normalize_station_name(name),
            pinyin_full=None,
            pinyin_initials=None,
            station_code=None,
            city_name=None,
            province_name=None,
            lon=lon,
            lat=30.9,
            match_status="ready",
            quality_flags_json=[],
        )
        db.add(station)
        db.flush()
        stations.append(station)
    journey = Journey(
        journey_code="rail-schema-test",
        traveled_at=date(2026, 8, 20),
        source_type="manual",
        note=None,
    )
    db.add(journey)
    db.flush()
    digest = f"sha256:{'c' * 64}"
    leg = JourneyLeg(
        journey_id=journey.id,
        leg_no=1,
        transport_mode="rail",
        dataset_version_id=None,
        city_id=None,
        line_id=None,
        route_variant_id=None,
        start_station_id=None,
        end_station_id=None,
        direction=None,
        resolution_status="resolved",
        resolution_message=None,
        candidate_digest=digest,
    )
    db.add(leg)
    db.flush()
    db.add(
        RailJourneyLegDetail(
            journey_leg_id=leg.id,
            travel_date=date(2026, 8, 20),
            train_no="G1",
            train_type="G",
            timetable_provider="manual",
            routing_profile="china_high_speed",
            scoring_version="2026-08-21-r0.2",
            route_hint="沪昆高速铁路",
            confidence=0.95,
            score_details_json=[{"code": "ordered_stations", "score": 1.0}],
            warnings_json=[],
            selected_candidate_digest=digest,
        )
    )
    for sequence, station in enumerate(stations, start=1):
        db.add(
            RailJourneyStop(
                journey_leg_id=leg.id,
                stop_sequence=sequence,
                station_id=station.id,
                raw_station_name=station.name_cn,
                arrival_time=None,
                departure_time=None,
                is_boarding=sequence == 1,
                is_alighting=sequence == 2,
                match_method="user_confirmed",
                match_confidence=1.0,
                locked_by_user=True,
            )
        )
    geometry = LineString([(121.327, 30.9), (120.212, 30.9)])
    db.add(
        RailJourneyEdgeSnapshot(
            journey_leg_id=leg.id,
            order_no=1,
            rail_dataset_version_id=dataset.id,
            provider_edge_ref="fixture:1",
            osm_way_id=2001,
            from_osm_node_id=1001,
            to_osm_node_id=1002,
            reversed=False,
            continuity_group=1,
            distance_m=170_000,
            geometry_wkb=geometry.wkb,
            geometry_sha256=sha256(geometry.wkb).hexdigest(),
            min_lon=geometry.bounds[0],
            min_lat=geometry.bounds[1],
            max_lon=geometry.bounds[2],
            max_lat=geometry.bounds[3],
            quality_flags_json=[],
        )
    )
    db.commit()

    assert db.scalar(select(func.count()).select_from(RailJourneyEdgeSnapshot)) == 1
    assert leg.transport_mode == "rail"

    invalid_leg = JourneyLeg(
        journey_id=journey.id,
        leg_no=2,
        transport_mode="bus",
        dataset_version_id=None,
        city_id=None,
        line_id=None,
        route_variant_id=None,
        start_station_id=None,
        end_station_id=None,
        direction=None,
        resolution_status="resolved",
        resolution_message=None,
        candidate_digest=digest,
    )
    db.add(invalid_leg)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
