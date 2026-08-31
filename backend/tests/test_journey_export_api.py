from __future__ import annotations

from factories import seed_linear_network, seed_transfer_network
from fastapi.testclient import TestClient
from lxml import etree
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models import Journey, JourneyLeg, JourneyLegEdge, RouteEdge, RouteVariant


def _path_candidate(
    client: TestClient,
    *,
    city_id: int,
    line_id: int,
    start_station_id: int,
    end_station_id: int,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": city_id,
            "line_id": line_id,
            "start_station_id": start_station_id,
            "end_station_id": end_station_id,
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "resolved"
    return payload["candidates"][0]


def _leg_input(
    *,
    city_id: int,
    line_id: int,
    start_station_id: int,
    end_station_id: int,
    candidate: dict[str, object],
) -> dict[str, object]:
    return {
        "city_id": city_id,
        "line_id": line_id,
        "start_station_id": start_station_id,
        "end_station_id": end_station_id,
        "direction": "auto",
        "via_station_ids": [],
        "candidate_id": candidate["candidate_id"],
        "candidate_digest": candidate["digest"],
    }


def test_preview_save_list_and_gpx_export(client: TestClient, db: Session) -> None:
    network = seed_linear_network(db)
    start_id, _, end_id = network.station_ids
    preview_response = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": network.line_id,
            "start_station_id": start_id,
            "end_station_id": end_id,
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["status"] == "resolved"
    candidate = preview["candidates"][0]
    assert len(candidate["edge_ids"]) == 2

    create_response = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "test-trip",
            "traveled_at": "2026-08-20",
            "source_type": "manual",
            "note": "回归测试",
            "legs": [
                {
                    "city_id": network.city_id,
                    "line_id": network.line_id,
                    "start_station_id": start_id,
                    "end_station_id": end_id,
                    "direction": "auto",
                    "via_station_ids": [],
                    "candidate_id": candidate["candidate_id"],
                    "candidate_digest": candidate["digest"],
                }
            ],
        },
    )
    assert create_response.status_code == 201
    journey = create_response.json()
    assert journey["legs"][0]["edge_ids"] == candidate["edge_ids"]

    listing = client.get("/api/v1/journeys").json()
    assert listing["total"] == 1
    assert listing["items"][0]["distance_m"] == 9600

    export_request = {
        "mode": "journeys",
        "max_segment_length_m": 25,
        "journey_ids": [journey["id"]],
    }
    export_preview = client.post("/api/v1/exports/preview", json=export_request)
    assert export_preview.status_code == 200
    summary = export_preview.json()
    assert summary["edge_count"] == 2
    assert summary["blocking_errors"] == []

    gpx_response = client.post(
        "/api/v1/exports/gpx",
        json={**export_request, "preview_token": summary["preview_token"]},
    )
    assert gpx_response.status_code == 200
    assert gpx_response.headers["content-type"].startswith("application/gpx+xml")
    root = etree.fromstring(gpx_response.content)
    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"
    points = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
    assert len(points) > 100
    assert root.findall(".//{http://www.topografix.com/GPX/1/1}time") == []


def test_journey_list_is_paginated_without_n_plus_one_queries(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    for index in range(25):
        journey = Journey(
            journey_code=f"page-trip-{index:02d}",
            traveled_at=None,
            source_type="manual",
            note=f"分页 {index}",
        )
        db.add(journey)
        db.flush()
        leg = JourneyLeg(
            journey_id=journey.id,
            leg_no=1,
            transport_mode="metro",
            dataset_version_id=network.dataset_id,
            city_id=network.city_id,
            line_id=network.line_id,
            route_variant_id=network.variant_id,
            start_station_id=network.station_ids[0],
            end_station_id=network.station_ids[-1],
            direction="正向",
            resolution_status="resolved",
            candidate_digest=f"sha256:{index:064x}",
        )
        db.add(leg)
        db.flush()
        for order_no, edge_id in enumerate(network.edge_ids, start=1):
            db.add(
                JourneyLegEdge(
                    journey_leg_id=leg.id,
                    route_edge_id=edge_id,
                    order_no=order_no,
                    reversed=False,
                )
            )
    db.commit()

    from app.db.session import engine

    select_statements: list[str] = []

    def capture_selects(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,  # type: ignore[no-untyped-def]
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_selects)
    try:
        response = client.get("/api/v1/journeys?limit=10&offset=10")
    finally:
        event.remove(engine, "before_cursor_execute", capture_selects)

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 25
    assert page["limit"] == 10
    assert page["offset"] == 10
    assert page["has_more"] is True
    assert len(page["items"]) == 10
    assert all(item["distance_m"] == 9600 for item in page["items"])
    assert len(select_statements) <= 7


def test_stale_candidate_is_rejected(client: TestClient, db: Session) -> None:
    network = seed_linear_network(db)
    start_id, _, end_id = network.station_ids
    response = client.post(
        "/api/v1/journeys",
        json={
            "source_type": "manual",
            "legs": [
                {
                    "city_id": network.city_id,
                    "line_id": network.line_id,
                    "start_station_id": start_id,
                    "end_station_id": end_id,
                    "direction": "auto",
                    "via_station_ids": [],
                    "candidate_id": "cand_stale",
                    "candidate_digest": f"sha256:{'0' * 64}",
                }
            ],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "candidate_expired"


def test_export_line_filter_only_includes_matching_legs(
    client: TestClient, db: Session
) -> None:
    first = seed_linear_network(db)
    second = seed_linear_network(
        db,
        suffix="-2",
        city_name="杭州",
        city_code="330100",
        line_name="二号测试线",
        start_lon=120.0,
    )
    first_candidate = _path_candidate(
        client,
        city_id=first.city_id,
        line_id=first.line_id,
        start_station_id=first.station_ids[0],
        end_station_id=first.station_ids[-1],
    )
    second_candidate = _path_candidate(
        client,
        city_id=second.city_id,
        line_id=second.line_id,
        start_station_id=second.station_ids[0],
        end_station_id=second.station_ids[-1],
    )
    create = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "two-lines",
            "source_type": "manual",
            "legs": [
                _leg_input(
                    city_id=first.city_id,
                    line_id=first.line_id,
                    start_station_id=first.station_ids[0],
                    end_station_id=first.station_ids[-1],
                    candidate=first_candidate,
                ),
                _leg_input(
                    city_id=second.city_id,
                    line_id=second.line_id,
                    start_station_id=second.station_ids[0],
                    end_station_id=second.station_ids[-1],
                    candidate=second_candidate,
                ),
            ],
        },
    )
    assert create.status_code == 201

    preview = client.post(
        "/api/v1/exports/preview",
        json={
            "mode": "journeys",
            "max_segment_length_m": None,
            "line_id": second.line_id,
        },
    )
    assert preview.status_code == 200
    summary = preview.json()
    assert summary["journey_count"] == 1
    assert summary["edge_count"] == 2
    assert summary["dataset_version_ids"] == [second.dataset_id]

    download = client.post(
        "/api/v1/exports/gpx",
        json={
            "mode": "journeys",
            "max_segment_length_m": None,
            "line_id": second.line_id,
            "preview_token": summary["preview_token"],
        },
    )
    assert download.status_code == 200
    points = etree.fromstring(download.content).findall(
        ".//{http://www.topografix.com/GPX/1/1}trkpt"
    )
    assert points
    assert all(float(point.attrib["lon"]) < 121 for point in points)


def test_export_blocks_saved_edges_and_variants_that_fail_quality_gate(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    candidate = _path_candidate(
        client,
        city_id=network.city_id,
        line_id=network.line_id,
        start_station_id=network.station_ids[0],
        end_station_id=network.station_ids[-1],
    )
    create = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "quality-gate",
            "source_type": "manual",
            "legs": [
                _leg_input(
                    city_id=network.city_id,
                    line_id=network.line_id,
                    start_station_id=network.station_ids[0],
                    end_station_id=network.station_ids[-1],
                    candidate=candidate,
                )
            ],
        },
    )
    journey_id = create.json()["id"]

    edge = db.get(RouteEdge, network.edge_ids[0])
    assert edge is not None
    edge.quality_status = "blocked"
    db.commit()
    blocked_edge = client.post(
        "/api/v1/exports/preview",
        json={"mode": "coverage", "journey_ids": [journey_id]},
    )
    assert blocked_edge.status_code == 409
    assert blocked_edge.json()["error"]["code"] == "export_blocked"

    edge.quality_status = "ready"
    variant = db.get(RouteVariant, network.variant_id)
    assert variant is not None
    variant.quality_status = "blocked"
    db.commit()
    blocked_variant = client.post(
        "/api/v1/exports/preview",
        json={"mode": "coverage", "journey_ids": [journey_id]},
    )
    assert blocked_variant.status_code == 409
    assert blocked_variant.json()["error"]["code"] == "export_blocked"


def test_coverage_groups_adjacent_edges_and_splits_disconnected_legs(
    client: TestClient, db: Session
) -> None:
    first = seed_linear_network(db)
    second = seed_linear_network(
        db,
        suffix="-2",
        city_name="杭州",
        city_code="330100",
        line_name="二号测试线",
        start_lon=120.0,
    )
    first_candidate = _path_candidate(
        client,
        city_id=first.city_id,
        line_id=first.line_id,
        start_station_id=first.station_ids[0],
        end_station_id=first.station_ids[-1],
    )
    second_candidate = _path_candidate(
        client,
        city_id=second.city_id,
        line_id=second.line_id,
        start_station_id=second.station_ids[0],
        end_station_id=second.station_ids[-1],
    )
    created = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "coverage-segments",
            "source_type": "manual",
            "legs": [
                _leg_input(
                    city_id=first.city_id,
                    line_id=first.line_id,
                    start_station_id=first.station_ids[0],
                    end_station_id=first.station_ids[-1],
                    candidate=first_candidate,
                ),
                _leg_input(
                    city_id=second.city_id,
                    line_id=second.line_id,
                    start_station_id=second.station_ids[0],
                    end_station_id=second.station_ids[-1],
                    candidate=second_candidate,
                ),
            ],
        },
    )
    journey_id = created.json()["id"]

    preview = client.post(
        "/api/v1/exports/preview",
        json={
            "mode": "coverage",
            "max_segment_length_m": None,
            "journey_ids": [journey_id],
        },
    )
    assert preview.status_code == 200
    assert preview.json()["track_count"] == 1
    assert preview.json()["segment_count"] == 2
    assert preview.json()["unique_edge_count"] == 4


def test_export_rejects_missing_explicit_journey_ids(client: TestClient) -> None:
    response = client.post(
        "/api/v1/exports/preview",
        json={"mode": "coverage", "journey_ids": [999_999]},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "export_blocked"


def test_unspecified_line_transfer_requires_confirmation_and_saves_all_edges(
    client: TestClient, db: Session
) -> None:
    network = seed_transfer_network(db)
    preview = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": None,
            "start_station_id": network.start_station_id,
            "end_station_id": network.end_station_id,
            "direction": "auto",
            "via_station_ids": [],
        },
    )
    assert preview.status_code == 200
    payload = preview.json()
    assert payload["status"] == "needs_review"
    assert len(payload["candidates"]) == 1
    candidate = payload["candidates"][0]
    assert candidate["direction_name"] == "1 次换乘"
    assert len(candidate["legs"]) == 2
    assert candidate["station_ids"] == [
        network.start_station_id,
        *candidate["legs"][0]["station_ids"][1:],
        *candidate["legs"][1]["station_ids"][1:],
    ]
    assert candidate["warnings"][0]["code"] == (
        "unspecified_line_requires_confirmation"
    )

    create = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "transfer-trip",
            "source_type": "manual",
            "legs": [
                {
                    "city_id": network.city_id,
                    "line_id": leg["line_id"],
                    "start_station_id": leg["start_station_id"],
                    "end_station_id": leg["end_station_id"],
                    "direction": "auto",
                    "via_station_ids": [],
                    "candidate_id": leg["candidate_id"],
                    "candidate_digest": leg["digest"],
                }
                for leg in candidate["legs"]
            ],
        },
    )
    assert create.status_code == 201
    saved = create.json()
    assert len(saved["legs"]) == 2
    assert [edge_id for leg in saved["legs"] for edge_id in leg["edge_ids"]] == list(
        network.edge_ids
    )


def test_unspecified_line_transfer_supports_an_ordered_via_station(
    client: TestClient, db: Session
) -> None:
    network = seed_transfer_network(db)
    preview = client.post(
        "/api/v1/paths/preview",
        json={
            "city_id": network.city_id,
            "line_id": None,
            "start_station_id": network.start_station_id,
            "end_station_id": network.end_station_id,
            "direction": "auto",
            "via_station_ids": [network.transfer_station_id],
        },
    )

    assert preview.status_code == 200
    payload = preview.json()
    assert payload["status"] == "needs_review"
    assert payload["candidates"]
    assert all(
        network.transfer_station_id in candidate["station_ids"]
        for candidate in payload["candidates"]
    )


def test_reverse_gpx_is_deterministic_and_keeps_requested_orientation(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    candidate = _path_candidate(
        client,
        city_id=network.city_id,
        line_id=network.line_id,
        start_station_id=network.station_ids[-1],
        end_station_id=network.station_ids[0],
    )
    create = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "reverse-gpx",
            "source_type": "manual",
            "legs": [
                _leg_input(
                    city_id=network.city_id,
                    line_id=network.line_id,
                    start_station_id=network.station_ids[-1],
                    end_station_id=network.station_ids[0],
                    candidate=candidate,
                )
            ],
        },
    )
    journey_id = create.json()["id"]
    options = {
        "mode": "journeys",
        "max_segment_length_m": None,
        "journey_ids": [journey_id],
    }
    first_preview = client.post("/api/v1/exports/preview", json=options).json()
    second_preview = client.post("/api/v1/exports/preview", json=options).json()
    assert first_preview["preview_token"] == second_preview["preview_token"]
    request = {**options, "preview_token": first_preview["preview_token"]}
    first_gpx = client.post("/api/v1/exports/gpx", json=request)
    second_gpx = client.post("/api/v1/exports/gpx", json=request)
    assert first_gpx.status_code == 200
    assert first_gpx.content == second_gpx.content
    points = etree.fromstring(first_gpx.content).findall(
        ".//{http://www.topografix.com/GPX/1/1}trkpt"
    )
    assert float(points[0].attrib["lon"]) == 121.5
    assert float(points[-1].attrib["lon"]) == 121.4


def test_journey_metadata_update_rejects_stale_concurrent_write(
    client: TestClient, db: Session
) -> None:
    network = seed_linear_network(db)
    candidate = _path_candidate(
        client,
        city_id=network.city_id,
        line_id=network.line_id,
        start_station_id=network.station_ids[0],
        end_station_id=network.station_ids[-1],
    )
    created = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "concurrent-update",
            "source_type": "manual",
            "legs": [
                _leg_input(
                    city_id=network.city_id,
                    line_id=network.line_id,
                    start_station_id=network.station_ids[0],
                    end_station_id=network.station_ids[-1],
                    candidate=candidate,
                )
            ],
        },
    ).json()
    stale_timestamp = created["updated_at"]
    first_update = client.patch(
        f"/api/v1/journeys/{created['id']}",
        json={"note": "first", "expected_updated_at": stale_timestamp},
    )
    assert first_update.status_code == 200

    stale_update = client.patch(
        f"/api/v1/journeys/{created['id']}",
        json={"note": "stale", "expected_updated_at": stale_timestamp},
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["error"]["code"] == "journey_update_conflict"
    current = client.get(f"/api/v1/journeys/{created['id']}").json()
    assert current["note"] == "first"
