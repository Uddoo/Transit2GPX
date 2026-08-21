from __future__ import annotations

import sqlite3
from pathlib import Path

from factories import seed_linear_network
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import StationAlias
from app.matching.names import normalize_station_name


def test_first_run_creates_complete_domain_schema(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200

    from app.core.config import get_settings

    database_path = Path(
        get_settings().resolved_database_url.removeprefix("sqlite:///")
    )
    with sqlite3.connect(database_path) as connection:
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
        "import_batch",
        "import_row",
    } <= table_names
    assert {"station_fts", "station_spatial", "route_edge_spatial"} <= table_names
    assert {
        "station_fts_insert",
        "station_spatial_insert",
        "route_edge_spatial_insert",
    } <= trigger_names


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
