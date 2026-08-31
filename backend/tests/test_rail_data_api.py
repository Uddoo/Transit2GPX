from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import pytest
from factories import seed_linear_network
from fastapi.testclient import TestClient
from lxml import etree
from shapely import wkb
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Journey,
    RailDatasetVersion,
    RailJourneyEdgeSnapshot,
    RailJourneyLegDetail,
    RailStation,
    RailStationAlias,
)
from app.matching.names import normalize_station_name, pinyin_keys
from app.rail.importer import (
    RailImportError,
    execute_rail_import,
    load_graph_metadata,
    prepare_rail_dataset,
    rail_station_count,
)
from app.rail.sidecar import (
    EXPECTED_RAIL_PROFILES,
    RailAttributeRange,
    RailRoutePath,
    RailSidecarError,
    RailSidecarInfo,
    RailWayRange,
    fetch_sidecar_route,
    validate_loopback_url,
)

_RAIL_GPX_NAMESPACE = "https://transit2fog.local/gpx/rail/1"


def _write_graph_metadata(
    root: Path, graph_version: str, pbf_checksum: str = "a" * 64
) -> None:
    graph_dir = root / graph_version
    graph_dir.mkdir(parents=True)
    (graph_dir / "transit2fog-graph.json").write_text(
        json.dumps(
            {
                "graph_version": graph_version,
                "profile_version": "2026-08-21-r0.1",
                "pbf_sha256": pbf_checksum,
                "source_url": "https://download.geofabrik.de/asia/china.html",
                "source_timestamp": "2026-08-20",
                "extract_region": "fixture",
                "openrailrouting_commit": "c8d4ef1",
                "graphhopper_version": "11.0-osm-reader-callbacks",
                "license": "ODbL-1.0",
            }
        ),
        encoding="utf-8",
    )


def _seed_rail_stations(db: Session) -> tuple[int, dict[str, int]]:
    dataset = RailDatasetVersion(
        source_name="OpenStreetMap/Geofabrik",
        source_url="https://download.geofabrik.de/asia/china.html",
        source_timestamp="2026-08-20",
        pbf_checksum="d" * 64,
        extract_region="test",
        graph_version="rail-station-search-test",
        profile_version="2026-08-21-r0.1",
        openrailrouting_version="c8d4ef1",
        graphhopper_version="11.0-osm-reader-callbacks",
        license="ODbL-1.0",
        status="ready",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.flush()
    station_ids: dict[str, int] = {}
    for osm_id, name, code, city, province, lon, lat in (
        (1001, "上海虹桥", "AOH", "上海", "上海", 121.327, 31.195),
        (1002, "上海", "SHH", "上海", "上海", 121.455, 31.251),
        (1003, "杭州东", "HGH", "杭州", "浙江", 120.212, 30.29),
    ):
        pinyin_full, pinyin_initials = pinyin_keys(name)
        station = RailStation(
            rail_dataset_version_id=dataset.id,
            osm_type="node",
            osm_id=osm_id,
            name_cn=name,
            name_en=None,
            normalized_name=normalize_station_name(name),
            pinyin_full=pinyin_full,
            pinyin_initials=pinyin_initials,
            station_code=code,
            city_name=city,
            province_name=province,
            lon=lon,
            lat=lat,
            match_status="ready",
            quality_flags_json=[],
        )
        db.add(station)
        db.flush()
        station_ids[name] = station.id
    db.add(
        RailStationAlias(
            station_id=station_ids["上海虹桥"],
            alias="虹桥火车站",
            normalized_alias=normalize_station_name("虹桥火车站"),
            alias_type="common_name",
            source="test",
        )
    )
    db.commit()
    return dataset.id, station_ids


def _seed_next_rail_dataset(
    db: Session,
    *,
    source_dataset_id: int,
    graph_version: str = "rail-station-search-next",
    pbf_checksum: str = "e" * 64,
) -> tuple[int, dict[str, int]]:
    dataset = RailDatasetVersion(
        source_name="OpenStreetMap/Geofabrik",
        source_url="https://download.geofabrik.de/asia/china.html",
        source_timestamp="2026-08-21",
        pbf_checksum=pbf_checksum,
        extract_region="test",
        graph_version=graph_version,
        profile_version="2026-08-21-r0.1",
        openrailrouting_version="c8d4ef1",
        graphhopper_version="11.0-osm-reader-callbacks",
        license="ODbL-1.0",
        status="ready",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.flush()
    station_ids: dict[str, int] = {}
    source_stations = db.scalars(
        select(RailStation)
        .where(RailStation.rail_dataset_version_id == source_dataset_id)
        .order_by(RailStation.osm_id)
    ).all()
    for source in source_stations:
        station = RailStation(
            rail_dataset_version_id=dataset.id,
            osm_type=source.osm_type,
            osm_id=source.osm_id,
            name_cn=source.name_cn,
            name_en=source.name_en,
            normalized_name=source.normalized_name,
            pinyin_full=source.pinyin_full,
            pinyin_initials=source.pinyin_initials,
            station_code=source.station_code,
            city_name=source.city_name,
            province_name=source.province_name,
            lon=source.lon,
            lat=source.lat,
            match_status="ready",
            quality_flags_json=[],
        )
        db.add(station)
        db.flush()
        station_ids[station.name_cn] = station.id
    db.commit()
    return dataset.id, station_ids


def test_active_graph_pointer_resolves_to_immutable_version(tmp_path: Path) -> None:
    graph_version = "china-20260815-r3.1"
    _write_graph_metadata(tmp_path, graph_version)
    (tmp_path / "active.json").write_text(
        json.dumps({"graph_version": graph_version}), encoding="utf-8"
    )

    metadata = load_graph_metadata(tmp_path, "active")

    assert metadata["graph_version"] == graph_version


def test_legacy_graph_metadata_filename_remains_readable(tmp_path: Path) -> None:
    graph_version = "china-legacy"
    _write_graph_metadata(tmp_path, graph_version)
    graph_dir = tmp_path / graph_version
    (graph_dir / "transit2fog-graph.json").rename(graph_dir / "metro2fog-graph.json")

    metadata = load_graph_metadata(tmp_path, graph_version)

    assert metadata["graph_version"] == graph_version


def test_active_graph_pointer_cannot_escape_graph_root(tmp_path: Path) -> None:
    nested_root = tmp_path / "nested"
    nested_root.mkdir()
    _write_graph_metadata(nested_root, "outside")
    (tmp_path / "active.json").write_text(
        json.dumps({"graph_version": "nested/outside"}), encoding="utf-8"
    )

    with pytest.raises(RailImportError, match="超出图数据目录"):
        load_graph_metadata(tmp_path, "active")


def _mock_resolver_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    *,
    graph_version: str = "rail-station-search-test",
    pbf_sha256: str = "d" * 64,
) -> None:
    monkeypatch.setattr(
        "app.rail.resolver.fetch_sidecar_info",
        lambda _url, _timeout: RailSidecarInfo(
            version="11.0",
            profiles=frozenset(EXPECTED_RAIL_PROFILES),
            bbox=(69.0, 18.0, 135.0, 54.0),
            import_date="2026-08-21T00:00:00Z",
            data_date="2026-08-20T00:00:00Z",
            graph_version=graph_version,
            pbf_sha256=pbf_sha256,
            profile_version="2026-08-21-r0.1",
            openrailrouting_commit="c8d4ef1",
        ),
    )


def _seed_graph_dataset(db: Session, graph_version: str) -> RailDatasetVersion:
    dataset = RailDatasetVersion(
        source_name="OpenStreetMap/Geofabrik",
        source_url="https://download.geofabrik.de/asia/china.html",
        source_timestamp="2026-08-20",
        pbf_checksum="a" * 64,
        extract_region="fixture",
        graph_version=graph_version,
        profile_version="2026-08-21-r0.1",
        openrailrouting_version="c8d4ef1",
        graphhopper_version="11.0-osm-reader-callbacks",
        license="ODbL-1.0",
        status="ready",
        quality_flags_json=[],
    )
    db.add(dataset)
    db.commit()
    return dataset


def test_rail_status_is_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/rail/data/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "disabled",
        "enabled": False,
        "sidecar_available": False,
        "rail_dataset_version_id": None,
        "dataset_status": None,
        "station_count": 0,
        "graph_version": None,
        "profile_version": None,
        "sidecar_graph_version": None,
        "sidecar_profile_version": None,
        "sidecar_pbf_checksum": None,
        "pbf_checksum": None,
        "source_url": None,
        "source_timestamp": None,
        "extract_region": None,
        "license": None,
        "profiles": [],
        "bbox": None,
        "error_code": None,
        "error_message": None,
    }


def test_rail_status_reports_ready_graph(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    graph_version = "fixture-20260821"
    _write_graph_metadata(tmp_path, graph_version)
    _seed_graph_dataset(db, graph_version)
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", graph_version)
    monkeypatch.setattr(settings, "rail_graph_root", tmp_path)
    monkeypatch.setattr(
        "app.api.rail_data.fetch_sidecar_info",
        lambda _url, _timeout: RailSidecarInfo(
            version="11.0",
            profiles=frozenset({"china_high_speed", "china_emu", "china_conventional"}),
            bbox=(120.0, 29.0, 122.0, 32.0),
            import_date="2026-08-21T00:00:00Z",
            data_date="2026-08-20T00:00:00Z",
            graph_version=graph_version,
            pbf_sha256="a" * 64,
            profile_version="2026-08-21-r0.1",
            openrailrouting_commit="c8d4ef1",
        ),
    )

    payload = client.get("/api/v1/rail/data/status").json()

    assert payload["status"] == "ready"
    assert payload["sidecar_available"] is True
    assert payload["graph_version"] == graph_version
    assert payload["pbf_checksum"] == "a" * 64
    assert payload["profiles"] == [
        "china_conventional",
        "china_emu",
        "china_high_speed",
    ]
    assert payload["sidecar_graph_version"] == graph_version


def test_rail_status_rejects_running_sidecar_for_another_graph(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    graph_version = "fixture-20260821"
    _write_graph_metadata(tmp_path, graph_version)
    _seed_graph_dataset(db, graph_version)
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", graph_version)
    monkeypatch.setattr(settings, "rail_graph_root", tmp_path)
    monkeypatch.setattr(
        "app.api.rail_data.fetch_sidecar_info",
        lambda _url, _timeout: RailSidecarInfo(
            version="11.0",
            profiles=frozenset(EXPECTED_RAIL_PROFILES),
            bbox=(69.0, 18.0, 135.0, 54.0),
            import_date="2026-08-21T00:00:00Z",
            data_date="2026-08-20T00:00:00Z",
            graph_version="another-graph",
            pbf_sha256="b" * 64,
            profile_version="another-profile",
            openrailrouting_commit="another-commit",
        ),
    )

    payload = client.get("/api/v1/rail/data/status").json()

    assert payload["status"] == "version_mismatch"
    assert payload["error_code"] == "rail_sidecar_graph_version_mismatch"
    assert payload["graph_version"] == graph_version
    assert payload["sidecar_graph_version"] == "another-graph"


def test_rail_status_degrades_without_blocking_api(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    graph_version = "fixture-20260821"
    _write_graph_metadata(tmp_path, graph_version)
    _seed_graph_dataset(db, graph_version)
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", graph_version)
    monkeypatch.setattr(settings, "rail_graph_root", tmp_path)

    def unavailable(_url: str, _timeout: float) -> RailSidecarInfo:
        raise RailSidecarError("rail_sidecar_unavailable", "铁路路径服务当前不可用。")

    monkeypatch.setattr("app.api.rail_data.fetch_sidecar_info", unavailable)

    rail_response = client.get("/api/v1/rail/data/status")
    health_response = client.get("/healthz")

    assert rail_response.status_code == 200
    assert rail_response.json()["status"] == "unavailable"
    assert health_response.status_code == 200


def test_rail_pbf_station_import_is_version_bound_and_filters_subway(
    db: Session, tmp_path: Path
) -> None:
    pbf_path = tmp_path / "fixture.osm.pbf"
    pbf_path.write_bytes(b"version-bound-pbf")
    checksum = hashlib.sha256(pbf_path.read_bytes()).hexdigest()
    graph_version = "rail-import-test"
    _write_graph_metadata(tmp_path, graph_version, checksum)
    dataset = prepare_rail_dataset(db, graph_root=tmp_path, graph_version=graph_version)

    def fake_reader(_path: Path, *, layer: str, where: str) -> gpd.GeoDataFrame:
        assert "railway" in where
        if layer != "points":
            return gpd.GeoDataFrame(
                {"geometry": []}, geometry="geometry", crs="EPSG:4326"
            )
        return gpd.GeoDataFrame(
            [
                {
                    "osm_id": "1001",
                    "name": "上海虹桥",
                    "ref": None,
                    "other_tags": (
                        '"railway"=>"station","train"=>"yes",'
                        '"name:en"=>"Shanghai Hongqiao",'
                        '"alt_name"=>"虹桥火车站",'
                        '"railway:ref"=>"AOH","addr:city"=>"上海",'
                        '"addr:province"=>"上海"'
                    ),
                    "geometry": Point(121.327, 31.195),
                },
                {
                    "osm_id": "1002",
                    "name": "虹桥2号航站楼",
                    "ref": None,
                    "other_tags": (
                        '"railway"=>"station","station"=>"subway",'
                        '"subway"=>"yes","train"=>"no"'
                    ),
                    "geometry": Point(121.326, 31.194),
                },
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )

    imported = execute_rail_import(
        db,
        dataset_id=dataset.id,
        pbf_path=pbf_path,
        frame_reader=fake_reader,
    )

    db.refresh(dataset)
    station = db.scalar(select(RailStation).where(RailStation.name_cn == "上海虹桥"))
    assert imported == 1
    assert dataset.status == "ready"
    assert rail_station_count(db, dataset.id) == 1
    assert station is not None
    assert station.station_code == "AOH"
    assert station.city_name == "上海"
    assert (
        db.scalar(
            select(RailStationAlias).where(RailStationAlias.station_id == station.id)
        ).alias
        == "虹桥火车站"
    )


def test_rail_import_rejects_pbf_checksum_drift(db: Session, tmp_path: Path) -> None:
    graph_version = "rail-checksum-test"
    _write_graph_metadata(tmp_path, graph_version)
    dataset = prepare_rail_dataset(db, graph_root=tmp_path, graph_version=graph_version)
    pbf_path = tmp_path / "wrong.osm.pbf"
    pbf_path.write_bytes(b"wrong")

    with pytest.raises(RuntimeError, match="SHA-256"):
        execute_rail_import(db, dataset_id=dataset.id, pbf_path=pbf_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8989",
        "http://example.com:8989",
        "http://user:pass@127.0.0.1:8989",
    ],
)
def test_sidecar_url_rejects_non_loopback_or_credentials(url: str) -> None:
    with pytest.raises(RailSidecarError, match="loopback"):
        validate_loopback_url(url)


@pytest.mark.parametrize("query", ["上海虹桥", "shhq", "AOH", "虹桥火车站"])
def test_rail_station_search_supports_name_pinyin_code_and_alias(
    client: TestClient, db: Session, query: str
) -> None:
    dataset_id, station_ids = _seed_rail_stations(db)

    response = client.get(
        "/api/v1/rail/stations/search",
        params={"q": query, "rail_dataset_version_id": dataset_id},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == station_ids["上海虹桥"]
    assert response.json()[0]["match_score"] >= 96


def test_rail_station_search_can_filter_city(client: TestClient, db: Session) -> None:
    dataset_id, station_ids = _seed_rail_stations(db)

    response = client.get(
        "/api/v1/rail/stations/search",
        params={
            "q": "东",
            "rail_dataset_version_id": dataset_id,
            "city_name": "杭州",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [station_ids["杭州东"]]


def test_sidecar_route_parses_geometry_and_osm_way_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "paths": [
            {
                "distance": 1200.5,
                "time": 60_000,
                "points": {
                    "coordinates": [[121.0, 31.0], [121.1, 31.1], [121.2, 31.2]]
                },
                "details": {
                    "osm_way_id": [[0, 1, 101], [1, 2, 102]],
                    "max_speed": [[0, 2, 250.0]],
                    "rail_average_speed": [[0, 2, 270.0]],
                    "railway_class": [[0, 2, "rail"]],
                    "railway_service": [[0, 2, "none"]],
                    "electrified": [[0, 2, "contact_line"]],
                },
            }
        ]
    }
    monkeypatch.setattr(
        "app.rail.sidecar.urlopen",
        lambda _request, timeout: (
            BytesIO(json.dumps(payload).encode()) if timeout == 2.0 else None
        ),
    )

    route = fetch_sidecar_route(
        "http://127.0.0.1:8989",
        2.0,
        points=((31.0, 121.0), (31.2, 121.2)),
        profile="china_conventional",
    )

    assert route.distance_m == 1200.5
    assert route.coordinates[-1] == (121.2, 31.2)
    assert [item.osm_way_id for item in route.way_ranges] == [101, 102]
    assert {(item.attribute, item.value) for item in route.attribute_ranges} >= {
        ("max_speed", 250.0),
        ("railway_service", "none"),
        ("electrified", "contact_line"),
    }


def test_rail_path_preview_preserves_order_and_deduplicates_geometry(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dataset_id, station_ids = _seed_rail_stations(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", "rail-station-search-test")
    _mock_resolver_sidecar(monkeypatch)
    requested_points: list[tuple[tuple[float, float], ...]] = []

    def fake_route(
        _base_url: str,
        _timeout_seconds: float,
        *,
        points: tuple[tuple[float, float], ...],
        profile: str,
    ) -> RailRoutePath:
        requested_points.append(points)
        middle = (121.4, 31.3) if profile == "china_conventional" else (121.3, 31.2)
        return RailRoutePath(
            profile=profile,
            distance_m=180_000,
            duration_ms=3_600_000,
            coordinates=((121.327, 31.195), middle, (120.212, 30.29)),
            way_ranges=(RailWayRange(0, 2, 999),),
            attribute_ranges=(
                RailAttributeRange("max_speed", 0, 2, 250.0),
                RailAttributeRange("rail_average_speed", 0, 2, 270.0),
                RailAttributeRange("railway_class", 0, 2, "rail"),
                RailAttributeRange("railway_service", 0, 2, "none"),
                RailAttributeRange("electrified", 0, 2, "contact_line"),
            ),
        )

    monkeypatch.setattr("app.rail.resolver.fetch_sidecar_route", fake_route)

    response = client.post(
        "/api/v1/paths/preview",
        json={
            "mode": "rail",
            "travel_date": "2026-08-20",
            "train_no": "G1",
            "train_type": "G",
            "start_station_id": station_ids["上海虹桥"],
            "via_station_ids": [station_ids["上海"]],
            "end_station_id": station_ids["杭州东"],
            "route_hint": "沪昆高速铁路",
        },
    )

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["status"] == "needs_review"
    assert len(response_payload["candidates"]) == 2
    assert response_payload["candidates"][0]["mode"] == "rail"
    assert response_payload["candidates"][0]["routing_profile"] == "china_high_speed"
    assert response_payload["candidates"][0]["station_ids"] == [
        station_ids["上海虹桥"],
        station_ids["上海"],
        station_ids["杭州东"],
    ]
    assert response_payload["candidates"][0]["way_ranges"][0]["osm_way_id"] == 999
    score_codes = {
        item["code"] for item in response_payload["candidates"][0]["score_details"]
    }
    assert {
        "train_profile_preference",
        "ordered_stations",
        "train_compatibility",
        "mainline_ratio",
        "railway_class",
        "osm_route_relation",
        "distance_rationality",
        "scoring_version",
    } <= score_codes
    assert (
        response_payload["candidates"][0]["score"]
        > response_payload["candidates"][1]["score"]
    )
    assert response_payload["candidates"][0]["can_commit"] is True
    assert all(len(points) == 3 for points in requested_points)


def test_rail_path_preview_rejects_sidecar_for_another_graph(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _dataset_id, station_ids = _seed_rail_stations(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", "rail-station-search-test")
    _mock_resolver_sidecar(
        monkeypatch,
        graph_version="another-graph",
        pbf_sha256="e" * 64,
    )
    monkeypatch.setattr(
        "app.rail.resolver.fetch_sidecar_route",
        lambda *_args, **_kwargs: pytest.fail("identity mismatch must stop routing"),
    )

    response = client.post(
        "/api/v1/paths/preview",
        json={
            "mode": "rail",
            "travel_date": "2026-08-20",
            "train_type": "G",
            "start_station_id": station_ids["上海虹桥"],
            "end_station_id": station_ids["杭州东"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "rail_sidecar_graph_version_mismatch"


def test_rail_journey_saves_and_reopens_without_sidecar(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_id, station_ids = _seed_rail_stations(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", "rail-station-search-test")
    _mock_resolver_sidecar(monkeypatch)

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
            distance_m=180_000,
            duration_ms=3_600_000,
            coordinates=((121.327, 31.195), (121.0, 31.0), (120.212, 30.29)),
            way_ranges=(RailWayRange(0, 1, 901), RailWayRange(1, 2, 902)),
        )

    monkeypatch.setattr("app.rail.resolver.fetch_sidecar_route", fake_route)
    facts = {
        "mode": "rail",
        "travel_date": "2026-08-20",
        "train_no": "G1",
        "train_type": "G",
        "start_station_id": station_ids["上海虹桥"],
        "via_station_ids": [],
        "end_station_id": station_ids["杭州东"],
        "route_hint": "沪昆高速铁路",
    }
    preview = client.post("/api/v1/paths/preview", json=facts)
    candidate = preview.json()["candidates"][0]

    create = client.post(
        "/api/v1/journeys",
        json={
            "source_type": "manual",
            "note": "铁路快照测试",
            "legs": [
                {
                    **facts,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_digest": candidate["digest"],
                }
            ],
        },
    )

    assert create.status_code == 201
    saved = create.json()
    assert saved["traveled_at"] == "2026-08-20"
    assert saved["legs"][0]["transport_mode"] == "rail"
    assert saved["legs"][0]["rail_dataset_version_id"] == dataset_id
    assert saved["legs"][0]["candidate_digest"] == candidate["digest"]
    assert saved["legs"][0]["timetable_provider"] == "manual"
    assert saved["legs"][0]["scoring_version"] == "2026-08-21-r0.2"
    detail = db.scalar(select(RailJourneyLegDetail))
    assert detail is not None
    assert detail.score_details_json == candidate["score_details"]
    assert detail.warnings_json == candidate["warnings"]
    snapshots = db.scalars(
        select(RailJourneyEdgeSnapshot).order_by(RailJourneyEdgeSnapshot.order_no)
    ).all()
    assert [snapshot.osm_way_id for snapshot in snapshots] == [901, 902]
    assert all(len(snapshot.geometry_sha256) == 64 for snapshot in snapshots)
    snapshot_coordinates: list[tuple[float, float]] = []
    for snapshot in snapshots:
        geometry = wkb.loads(snapshot.geometry_wkb)
        assert (
            hashlib.sha256(snapshot.geometry_wkb).hexdigest()
            == snapshot.geometry_sha256
        )
        coordinates = list(geometry.coords)
        snapshot_coordinates.extend(
            coordinates if not snapshot_coordinates else coordinates[1:]
        )
    assert snapshot_coordinates == [
        tuple(point) for point in candidate["geometry"]["coordinates"]
    ]

    duplicate_create = client.post(
        "/api/v1/journeys",
        json={
            "source_type": "manual",
            "note": "同版本铁路 coverage 去重测试",
            "legs": [
                {
                    **facts,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_digest": candidate["digest"],
                }
            ],
        },
    )
    assert duplicate_create.status_code == 201
    duplicate = duplicate_create.json()

    def unavailable(*_args: object, **_kwargs: object) -> RailRoutePath:
        raise AssertionError("saved journey must not call the sidecar")

    monkeypatch.setattr("app.rail.resolver.fetch_sidecar_route", unavailable)
    reopened = client.get(f"/api/v1/journeys/{saved['id']}")
    assert reopened.status_code == 200
    assert reopened.json()["legs"][0]["candidate_digest"] == candidate["digest"]

    export_request = {
        "mode": "journeys",
        "journey_ids": [saved["id"]],
        "max_segment_length_m": 25,
        "rail_max_segment_length_m": 200,
    }
    export_preview = client.post("/api/v1/exports/preview", json=export_request)
    assert export_preview.status_code == 200
    export_summary = export_preview.json()
    assert export_summary["dataset_version_ids"] == []
    assert export_summary["rail_dataset_version_ids"] == [dataset_id]
    assert export_summary["rail_graph_versions"] == ["rail-station-search-test"]
    gpx = client.post(
        "/api/v1/exports/gpx",
        json={**export_request, "preview_token": export_summary["preview_token"]},
    )
    assert gpx.status_code == 200
    gpx_root = etree.fromstring(gpx.content)
    links = gpx_root.findall(".//{http://www.topografix.com/GPX/1/1}link")
    assert links[0].attrib["href"] == "https://www.openstreetmap.org/copyright"
    description = gpx_root.findtext(
        ".//{http://www.topografix.com/GPX/1/1}metadata/"
        "{http://www.topografix.com/GPX/1/1}desc"
    )
    assert description is not None
    assert "rail-station-search-test" in description
    assert "2026-08-21-r0.1" in description
    snapshot_metadata = gpx_root.find(f".//{{{_RAIL_GPX_NAMESPACE}}}snapshot")
    assert snapshot_metadata is not None
    expected_geometry_hash = hashlib.sha256(
        json.dumps(candidate["geometry"]["coordinates"], separators=(",", ":")).encode()
    ).hexdigest()
    assert snapshot_metadata.attrib == {
        "journeyId": str(saved["id"]),
        "legNo": "1",
        "railDatasetVersionId": str(dataset_id),
        "graphVersion": "rail-station-search-test",
        "profileVersion": "2026-08-21-r0.1",
        "candidateDigest": candidate["digest"],
        "sourceGeometrySha256": expected_geometry_hash,
    }
    assert gpx_root.findall(".//{http://www.topografix.com/GPX/1/1}time") == []
    rail_points = gpx_root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
    assert len(rail_points) > 100

    coverage = client.post(
        "/api/v1/exports/preview",
        json={
            "mode": "coverage",
            "journey_ids": [saved["id"], duplicate["id"]],
            "max_segment_length_m": 25,
            "rail_max_segment_length_m": 200,
        },
    )
    assert coverage.status_code == 200
    coverage_summary = coverage.json()
    assert coverage_summary["edge_count"] == 4
    assert coverage_summary["unique_edge_count"] == 2
    assert coverage_summary["rail_dataset_version_ids"] == [dataset_id]


def test_rail_journey_rejects_browser_supplied_geometry(
    client: TestClient, db: Session
) -> None:
    _dataset_id, station_ids = _seed_rail_stations(db)

    response = client.post(
        "/api/v1/journeys",
        json={
            "source_type": "manual",
            "legs": [
                {
                    "mode": "rail",
                    "travel_date": "2026-08-20",
                    "train_type": "G",
                    "start_station_id": station_ids["上海虹桥"],
                    "end_station_id": station_ids["杭州东"],
                    "candidate_id": "rail_cand_fake",
                    "candidate_digest": f"sha256:{'f' * 64}",
                    "geometry": {"type": "LineString", "coordinates": []},
                }
            ],
        },
    )

    assert response.status_code == 422


def test_rail_dataset_compare_reports_station_and_journey_impact(
    client: TestClient, db: Session
) -> None:
    source_dataset_id, station_ids = _seed_rail_stations(db)
    target_dataset_id, _ = _seed_next_rail_dataset(
        db, source_dataset_id=source_dataset_id
    )
    changed_station = db.scalar(
        select(RailStation).where(
            RailStation.rail_dataset_version_id == target_dataset_id,
            RailStation.osm_id == 1001,
        )
    )
    removed_station = db.scalar(
        select(RailStation).where(
            RailStation.rail_dataset_version_id == target_dataset_id,
            RailStation.osm_id == 1003,
        )
    )
    assert changed_station is not None
    assert removed_station is not None
    changed_station.name_cn = "上海虹桥站"
    changed_station.lon += 0.0001
    db.delete(removed_station)
    added_station = RailStation(
        rail_dataset_version_id=target_dataset_id,
        osm_type="node",
        osm_id=1004,
        name_cn="嘉兴南",
        name_en=None,
        normalized_name=normalize_station_name("嘉兴南"),
        pinyin_full="jiaxingnan",
        pinyin_initials="jxn",
        station_code="EPH",
        city_name="嘉兴",
        province_name="浙江",
        lon=120.806,
        lat=30.691,
        match_status="ready",
        quality_flags_json=[],
    )
    db.add(added_station)
    source_journey = Journey(
        journey_code="rail-impact-fixture",
        traveled_at=None,
        source_type="manual",
        note=None,
    )
    db.add(source_journey)
    db.flush()
    # A journey only counts as affected when an immutable snapshot references
    # the source graph. Station form selections by themselves are not evidence.
    db.commit()

    response = client.get(
        "/api/v1/rail/data/compare",
        params={
            "from_graph_version": "rail-station-search-test",
            "to_graph_version": "rail-station-search-next",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["from_station_count"] == 3
    assert payload["to_station_count"] == 3
    assert payload["added_station_count"] == 1
    assert payload["removed_station_count"] == 1
    assert payload["changed_station_count"] == 1
    assert payload["unchanged_station_count"] == 1
    assert payload["affected_journey_count"] == 0
    assert {sample["changed_fields"][0] for sample in payload["samples"]} >= {
        "added",
        "removed",
    }
    changed_sample = next(
        sample for sample in payload["samples"] if sample["osm_id"] == 1001
    )
    assert changed_sample["changed_fields"] == ["name_cn", "lon"]
    assert station_ids["上海虹桥"] > 0


def test_rail_recompute_clones_journey_and_preserves_original_snapshot(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    metro_network = seed_linear_network(db)
    source_dataset_id, station_ids = _seed_rail_stations(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rail_enabled", True)
    monkeypatch.setattr(settings, "rail_graph_version", "rail-station-search-test")
    _mock_resolver_sidecar(monkeypatch)

    current_way_id = 901

    def fake_route(
        _base_url: str,
        _timeout_seconds: float,
        *,
        points: tuple[tuple[float, float], ...],
        profile: str,
    ) -> RailRoutePath:
        return RailRoutePath(
            profile=profile,
            distance_m=180_000,
            duration_ms=3_600_000,
            coordinates=(points[0][::-1], (121.0, 31.0), points[-1][::-1]),
            way_ranges=(RailWayRange(0, 2, current_way_id),),
        )

    monkeypatch.setattr("app.rail.resolver.fetch_sidecar_route", fake_route)
    metro_facts = {
        "mode": "metro",
        "city_id": metro_network.city_id,
        "line_id": metro_network.line_id,
        "start_station_id": metro_network.station_ids[0],
        "end_station_id": metro_network.station_ids[-1],
        "direction": "auto",
        "via_station_ids": [],
    }
    metro_candidate = client.post("/api/v1/paths/preview", json=metro_facts).json()[
        "candidates"
    ][0]
    facts = {
        "mode": "rail",
        "travel_date": "2026-08-20",
        "train_no": "G1",
        "train_type": "G",
        "start_station_id": station_ids["上海虹桥"],
        "via_station_ids": [],
        "end_station_id": station_ids["杭州东"],
        "route_hint": "沪昆高速铁路",
    }
    candidate = client.post("/api/v1/paths/preview", json=facts).json()["candidates"][0]
    saved = client.post(
        "/api/v1/journeys",
        json={
            "source_type": "manual",
            "note": "保留原始快照",
            "legs": [
                {
                    **metro_facts,
                    "candidate_id": metro_candidate["candidate_id"],
                    "candidate_digest": metro_candidate["digest"],
                },
                {
                    **facts,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_digest": candidate["digest"],
                },
            ],
        },
    ).json()
    original_snapshot = client.get(f"/api/v1/journeys/{saved['id']}").json()

    target_dataset_id, _target_station_ids = _seed_next_rail_dataset(
        db, source_dataset_id=source_dataset_id
    )
    monkeypatch.setattr(settings, "rail_graph_version", "rail-station-search-next")
    _mock_resolver_sidecar(
        monkeypatch,
        graph_version="rail-station-search-next",
        pbf_sha256="e" * 64,
    )
    current_way_id = 9901

    preview = client.post(f"/api/v1/journeys/{saved['id']}/rail-recompute/preview")

    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["target_graph_version"] == "rail-station-search-next"
    assert preview_payload["legs"][0]["source_graph_version"] == (
        "rail-station-search-test"
    )
    assert preview_payload["legs"][0]["leg_no"] == 2
    assert (
        preview_payload["legs"][0]["candidates"][0]["rail_dataset_version_id"]
        == target_dataset_id
    )
    selected = preview_payload["legs"][0]["candidates"][0]
    recomputed = client.post(
        f"/api/v1/journeys/{saved['id']}/rail-recompute",
        json={
            "target_graph_version": preview_payload["target_graph_version"],
            "selections": [
                {
                    "leg_no": 2,
                    "candidate_id": selected["candidate_id"],
                    "candidate_digest": selected["digest"],
                }
            ],
        },
    )

    assert recomputed.status_code == 201
    recomputed_payload = recomputed.json()
    assert recomputed_payload["id"] != saved["id"]
    assert recomputed_payload["source_type"] == "manual"
    assert recomputed_payload["legs"][0]["transport_mode"] == "metro"
    assert (
        recomputed_payload["legs"][0]["edge_ids"]
        == original_snapshot["legs"][0]["edge_ids"]
    )
    assert recomputed_payload["legs"][1]["graph_version"] == (
        "rail-station-search-next"
    )
    assert recomputed_payload["legs"][1]["osm_way_ids"] == [9901]
    assert "原行程保留不变" in recomputed_payload["note"]
    reopened_original = client.get(f"/api/v1/journeys/{saved['id']}").json()
    assert reopened_original == original_snapshot
    assert reopened_original["legs"][1]["graph_version"] == ("rail-station-search-test")
    assert reopened_original["legs"][1]["osm_way_ids"] == [901]
