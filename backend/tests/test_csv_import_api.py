from __future__ import annotations

from factories import seed_linear_network
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    ImportBatch,
    ImportRow,
    Journey,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RailJourneyLegDetail,
    RailStation,
    Station,
)
from app.matching.names import normalize_station_name, pinyin_keys
from app.rail.sidecar import (
    EXPECTED_RAIL_PROFILES,
    RailAttributeRange,
    RailRoutePath,
    RailSidecarInfo,
    RailWayRange,
)


def test_csv_review_and_transaction_commit(client: TestClient, db: Session) -> None:
    network = seed_linear_network(db)
    full, initials = pinyin_keys("甲站")
    db.add(
        Station(
            city_id=network.city_id,
            name_cn="甲站",
            name_en=None,
            normalized_name=normalize_station_name("甲站"),
            pinyin_full=full,
            pinyin_initials=initials,
            lon=121.9,
            lat=31.5,
            cluster_no=1,
        )
    )
    db.commit()
    content = (
        "journey_id,leg_no,city,line,start_station,end_station,traveled_at,direction,via_station,note\n"
        "csv-trip,1,上海,测试线,甲站,丙站,2026-08-20,,,测试导入\n"
    )
    upload = client.post(
        "/api/v1/import-batches",
        files={"file": ("journeys.csv", content.encode(), "text/csv")},
    )
    assert upload.status_code == 201
    batch = upload.json()
    assert batch["resolved_rows"] == 1

    rows = client.get(f"/api/v1/import-batches/{batch['id']}/rows").json()
    assert rows["total"] == 1
    assert rows["items"][0]["resolution_status"] == "resolved"

    commit = client.post(
        f"/api/v1/import-batches/{batch['id']}/commit",
        json={"strategy": "all"},
    )
    assert commit.status_code == 200
    assert commit.json()["status"] == "committed"
    listing = client.get("/api/v1/journeys").json()
    assert listing["total"] == 1
    assert listing["items"][0]["note"] == "测试导入"


def test_csv_rejects_non_utf8_and_missing_columns(client: TestClient) -> None:
    invalid_encoding = client.post(
        "/api/v1/import-batches",
        files={"file": ("bad.csv", b"\xff\xfe\x00", "text/csv")},
    )
    assert invalid_encoding.status_code == 422
    assert invalid_encoding.json()["error"]["code"] == "csv_encoding_invalid"

    missing = client.post(
        "/api/v1/import-batches",
        files={"file": ("missing.csv", b"city,line\nShanghai,2\n", "text/csv")},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "csv_columns_missing"


def test_csv_commits_two_leg_transfer_as_one_journey(
    client: TestClient, db: Session
) -> None:
    seed_linear_network(db)
    seed_linear_network(
        db,
        suffix="-2",
        city_name="杭州",
        city_code="330100",
        line_name="二号测试线",
        start_lon=120.0,
    )
    content = (
        "journey_id,leg_no,city,line,start_station,end_station,traveled_at,note\n"
        "transfer,1,上海,测试线,甲站,丙站,2026-08-20,=1+1\n"
        "transfer,2,杭州,二号测试线,甲站-2,丙站-2,2026-08-20,=1+1\n"
    )
    upload = client.post(
        "/api/v1/import-batches",
        files={"file": ("transfer.csv", content.encode(), "text/csv")},
    )
    assert upload.status_code == 201
    batch = upload.json()
    assert batch["resolved_rows"] == 2

    commit = client.post(
        f"/api/v1/import-batches/{batch['id']}/commit",
        json={"strategy": "all"},
    )
    assert commit.status_code == 200
    listing = client.get("/api/v1/journeys").json()
    assert listing["total"] == 1
    assert len(listing["items"][0]["legs"]) == 2
    assert listing["items"][0]["note"] == "=1+1"


def test_unified_csv_commits_metro_and_rail_as_one_mixed_journey(
    client: TestClient,
    db: Session,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    seed_linear_network(db)
    dataset = RailDatasetVersion(
        source_name="OpenStreetMap/Geofabrik",
        source_url="https://download.geofabrik.de/asia/china.html",
        source_timestamp="2026-08-20",
        pbf_checksum="f" * 64,
        extract_region="test",
        graph_version="csv-rail-test",
        profile_version="2026-08-21-r0.1",
        openrailrouting_version="c8d4ef1",
        graphhopper_version="11.0-osm-reader-callbacks",
        license="ODbL-1.0",
        status="ready",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.flush()
    for osm_id, name, lon, lat in (
        (8001, "上海虹桥", 121.327, 31.195),
        (8002, "杭州东", 120.212, 30.29),
    ):
        full, initials = pinyin_keys(name)
        db.add(
            RailStation(
                rail_dataset_version_id=dataset.id,
                osm_type="node",
                osm_id=osm_id,
                name_cn=name,
                name_en=None,
                normalized_name=normalize_station_name(name),
                pinyin_full=full,
                pinyin_initials=initials,
                station_code=None,
                city_name=None,
                province_name=None,
                lon=lon,
                lat=lat,
                match_status="ready",
                quality_flags_json=[],
            )
        )
    db.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", dataset.graph_version)
    monkeypatch.setattr(
        "app.rail.resolver.fetch_sidecar_info",
        lambda _url, _timeout: RailSidecarInfo(
            version="11.0",
            profiles=frozenset(EXPECTED_RAIL_PROFILES),
            bbox=(69.0, 18.0, 135.0, 54.0),
            import_date="2026-08-21T00:00:00Z",
            data_date="2026-08-20T00:00:00Z",
            graph_version=dataset.graph_version,
            pbf_sha256=dataset.pbf_checksum,
            profile_version=dataset.profile_version,
            openrailrouting_commit=dataset.openrailrouting_version,
        ),
    )

    def fake_route(
        _base_url: str,
        _timeout_seconds: float,
        *,
        points: tuple[tuple[float, float], ...],
        profile: str,
    ) -> RailRoutePath:
        del points
        return RailRoutePath(
            profile=profile,
            distance_m=159_000,
            duration_ms=3_600_000,
            coordinates=((121.327, 31.195), (121.0, 31.0), (120.212, 30.29)),
            way_ranges=(RailWayRange(0, 2, 9901),),
            attribute_ranges=(
                RailAttributeRange("max_speed", 0, 2, 250.0),
                RailAttributeRange("rail_average_speed", 0, 2, 270.0),
                RailAttributeRange("railway_class", 0, 2, "rail"),
                RailAttributeRange("railway_service", 0, 2, "none"),
                RailAttributeRange("electrified", 0, 2, "contact_line"),
            ),
        )

    monkeypatch.setattr("app.rail.resolver.fetch_sidecar_route", fake_route)
    content = (
        "journey_id,leg_no,mode,travel_date,train_no,train_type,city,line,"
        "from_station,to_station,via_stations,route_hint,direction,note\n"
        "mixed,1,metro,2026-08-20,,,上海,测试线,甲站,丙站,,,,混合行程\n"
        "mixed,2,rail,2026-08-20, g1 ,G,,,上海虹桥,杭州东,,,,混合行程\n"
    )
    upload = client.post(
        "/api/v1/import-batches",
        files={"file": ("mixed.csv", content.encode(), "text/csv")},
    )

    assert upload.status_code == 201
    assert upload.json()["resolved_rows"] == 2
    batch_id = upload.json()["id"]
    commit = client.post(
        f"/api/v1/import-batches/{batch_id}/commit", json={"strategy": "all"}
    )

    assert commit.status_code == 200
    listing = client.get("/api/v1/journeys").json()
    assert listing["total"] == 1
    assert [leg["transport_mode"] for leg in listing["items"][0]["legs"]] == [
        "metro",
        "rail",
    ]
    assert db.scalar(select(func.count()).select_from(RailJourneyEdgeSnapshot)) == 1
    rail_detail = db.scalar(select(RailJourneyLegDetail))
    assert rail_detail is not None
    assert rail_detail.train_no == "G1"
    assert rail_detail.timetable_provider == "csv"
    assert rail_detail.scoring_version == "2026-08-21-r0.2"


def test_csv_commit_failure_rolls_back_every_new_journey(
    client: TestClient, db: Session
) -> None:
    seed_linear_network(db)
    content = (
        "journey_id,city,line,start_station,end_station\n"
        "collision,上海,测试线,甲站,丙站\n"
        "other,上海,测试线,甲站,乙站\n"
    )
    upload = client.post(
        "/api/v1/import-batches",
        files={"file": ("rollback.csv", content.encode(), "text/csv")},
    )
    batch_id = upload.json()["id"]
    db.add(
        Journey(
            journey_code=f"csv-{batch_id}-collision",
            traveled_at=None,
            source_type="manual",
            note="forces unique conflict",
        )
    )
    db.commit()

    commit = client.post(
        f"/api/v1/import-batches/{batch_id}/commit",
        json={"strategy": "all"},
    )
    assert commit.status_code == 409
    assert commit.json()["error"]["code"] == "csv_commit_failed"
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Journey)) == 1
    batch = db.get(ImportBatch, batch_id)
    assert batch is not None and batch.status == "ready_for_review"
    rows = db.scalars(select(ImportRow).where(ImportRow.batch_id == batch_id)).all()
    assert all(row.resolution_status == "resolved" for row in rows)


def test_csv_pagination_malformed_rows_and_row_limit(
    client: TestClient,
    db: Session,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    seed_linear_network(db)
    content = (
        "journey_id,city,line,start_station,end_station\n"
        "one,上海,测试线,甲站,丙站\n"
        "two,上海,测试线,甲站,乙站\n"
        "three,上海,测试线,乙站,丙站\n"
    )
    upload = client.post(
        "/api/v1/import-batches",
        files={"file": ("paged.csv", content.encode(), "text/csv")},
    )
    batch_id = upload.json()["id"]
    second_page = client.get(
        f"/api/v1/import-batches/{batch_id}/rows", params={"limit": 2, "offset": 2}
    )
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 3
    assert [item["row_no"] for item in second_page.json()["items"]] == [4]

    malformed = client.post(
        "/api/v1/import-batches",
        files={
            "file": (
                "malformed.csv",
                b"city,line,start_station,end_station\nShanghai,1,A,B,extra\n",
                "text/csv",
            )
        },
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "csv_row_malformed"

    from app.api import csv_imports

    monkeypatch.setattr(csv_imports, "MAX_ROWS", 2)
    too_many = client.post(
        "/api/v1/import-batches",
        files={"file": ("too-many.csv", content.encode(), "text/csv")},
    )
    assert too_many.status_code == 413
    assert too_many.json()["error"]["code"] == "csv_too_many_rows"
