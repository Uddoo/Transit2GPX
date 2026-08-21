from __future__ import annotations

from factories import seed_branch_network, seed_linear_network, seed_loop_network
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_reverse_linear_path_preserves_reverse_edge_order(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    response = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": network.line_id,
            "start_station_id": network.station_ids[-1],
            "end_station_id": network.station_ids[0],
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert response.status_code == 200
    candidate = response.json()["candidates"][0]
    assert candidate["edge_ids"] == list(reversed(network.edge_ids))
    assert candidate["reversed_edges"] == [True, True]
    assert candidate["station_ids"] == list(reversed(network.station_ids))


def test_loop_returns_short_and_long_arc_candidates(
    client: TestClient, db: Session
) -> None:
    network = seed_loop_network(db)
    response = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": network.line_id,
            "start_station_id": network.station_ids[0],
            "end_station_id": network.station_ids[1],
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_review"
    assert sorted(
        len(candidate["edge_ids"]) for candidate in payload["candidates"]
    ) == [
        1,
        3,
    ]
    assert all(candidate["legs"] for candidate in payload["candidates"])


def test_city_routing_enforces_a_via_station_off_the_shortest_path(
    client: TestClient, db: Session
) -> None:
    network = seed_loop_network(db)
    response = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": None,
            "start_station_id": network.station_ids[0],
            "end_station_id": network.station_ids[1],
            "direction": "auto",
            "via_station_ids": [network.station_ids[3]],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_review"
    assert payload["candidates"]
    assert all(
        network.station_ids[3] in candidate["station_ids"]
        for candidate in payload["candidates"]
    )
    assert min(candidate["distance_m"] for candidate in payload["candidates"]) > 4000


def test_branch_shared_segment_is_ambiguous_but_branch_end_is_unique(
    client: TestClient, db: Session
) -> None:
    network = seed_branch_network(db)
    shared = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": network.line_id,
            "start_station_id": network.start_station_id,
            "end_station_id": network.shared_station_id,
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert shared.status_code == 200
    assert shared.json()["status"] == "needs_review"
    assert len(shared.json()["candidates"]) == 2

    branch_end = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": network.line_id,
            "start_station_id": network.shared_station_id,
            "end_station_id": network.second_end_station_id,
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert branch_end.status_code == 200
    assert branch_end.json()["status"] == "resolved"
    assert len(branch_end.json()["candidates"]) == 1
