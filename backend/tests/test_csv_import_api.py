from __future__ import annotations

from factories import seed_linear_network
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ImportBatch, ImportRow, Journey, Station
from app.matching.names import normalize_station_name, pinyin_keys


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
