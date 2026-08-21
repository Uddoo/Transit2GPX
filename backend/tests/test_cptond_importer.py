from __future__ import annotations

import geopandas as gpd
from factories import seed_linear_network
from shapely.geometry import LineString, Point
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import City, DatasetVersion, RouteStop, RouteVariant, Station


def _write_city_bundle(
    root,  # type: ignore[no-untyped-def]
    *,
    slug: str,
    city_code: str,
    city_name: str,
    routes: list[dict[str, object]],
    stops: list[dict[str, object]],
) -> None:
    route_frame = gpd.GeoDataFrame(routes, geometry="geometry", crs="EPSG:4326")
    stop_frame = gpd.GeoDataFrame(stops, geometry="geometry", crs="EPSG:4326")
    route_frame.to_file(root / f"{slug}_metro_routes.shp", encoding="UTF-8")
    stop_frame.to_file(root / f"{slug}_metro_stops.shp", encoding="UTF-8")
    del city_code, city_name


def _write_minimal_linear_bundle(root) -> None:  # type: ignore[no-untyped-def]
    _write_city_bundle(
        root,
        slug="linear",
        city_code="100",
        city_name="直线城",
        routes=[
            {
                "route_id": "linear-1",
                "route_cn": "1号线",
                "route_en": "Line 1",
                "city_code": "100",
                "city_cn": "直线城",
                "city_en": "Linear City",
                "loop": 0,
                "start_stop": "甲",
                "end_stop": "丙",
                "geometry": LineString([(110.0, 30.0), (110.05, 30.0), (110.1, 30.0)]),
            }
        ],
        stops=[
            {
                "stop_id": f"linear-{sequence}",
                "name_cn": name,
                "name_en": name,
                "route_id": "linear-1",
                "route_cn": "1号线",
                "city_code": "100",
                "city_cn": "直线城",
                "city_en": "Linear City",
                "sequence": sequence,
                "geometry": Point(lon, 30.0),
            }
            for sequence, (name, lon) in enumerate(
                (("甲", 110.0), ("乙", 110.05), ("丙", 110.1)), start=1
            )
        ],
    )


def _write_sciencedb_timeline_bundle(root) -> None:  # type: ignore[no-untyped-def]
    loop_stations = (
        ("东", "East", 120.0, 30.0),
        ("南", "South", 120.04, 30.0),
        ("西", "West", 120.04, 30.04),
        ("北", "North", 120.0, 30.04),
    )
    routes = gpd.GeoDataFrame(
        [
            {
                "route_cn": "时序1号线",
                "city_code": "310",
                "city_cn": "时序城",
                "loop": 0,
                "geometry": LineString([(121.0, 31.0), (121.05, 31.0), (121.1, 31.0)]),
            },
            {
                "route_cn": "时序环线",
                "city_code": "320",
                "city_cn": "时序环城",
                "loop": 1,
                "geometry": LineString(
                    [
                        (120.0, 30.0),
                        (120.04, 30.0),
                        (120.04, 30.04),
                        (120.0, 30.04),
                        (120.0, 30.0),
                    ]
                ),
            },
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    stations = gpd.GeoDataFrame(
        [
            *[
                {
                    "stop_id": f"timeline-{sequence}",
                    "name_cn": name,
                    "name_en": english_name,
                    "route_id": "timeline-1",
                    "route_cn": "时序1号线",
                    "city_code": "310",
                    "city_cn": "时序城",
                    "geometry": Point(lon, 31.0),
                }
                for sequence, (name, english_name, lon) in enumerate(
                    (
                        ("起点", "Start", 121.0),
                        ("中点", "Middle", 121.05),
                        ("终点", "End", 121.1),
                    ),
                    start=1,
                )
            ],
            *[
                {
                    "stop_id": f"timeline-loop-{sequence}",
                    "name_cn": name,
                    "name_en": english_name,
                    "route_id": "timeline-loop",
                    "route_cn": "时序环线",
                    "city_code": "320",
                    "city_cn": "时序环城",
                    "geometry": Point(lon, lat),
                }
                for sequence, (name, english_name, lon, lat) in enumerate(
                    loop_stations, start=1
                )
            ],
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    segments = gpd.GeoDataFrame(
        [
            *[
                {
                    "seg_id": f"segment-{sequence}",
                    "seg_seq": sequence,
                    "s_route_id": "timeline-1",
                    "e_route_id": "timeline-1",
                    "route_cn": "时序1号线",
                    "city_code": "310",
                    "city_cn": "时序城",
                    "s_name_cn": start_name,
                    "e_name_cn": end_name,
                    "s_stop_id": f"timeline-{sequence}",
                    "e_stop_id": f"timeline-{sequence + 1}",
                    "geometry": LineString([(start_lon, 31.0), (end_lon, 31.0)]),
                }
                for sequence, (start_name, end_name, start_lon, end_lon) in enumerate(
                    (
                        ("起点", "中点", 121.0, 121.05),
                        ("中点", "终点", 121.05, 121.1),
                    ),
                    start=1,
                )
            ],
            {
                "seg_id": "loop-direction-anchor",
                "seg_seq": 0,
                "s_route_id": "timeline-loop",
                "e_route_id": "timeline-loop",
                "route_cn": "时序环线",
                "city_code": "320",
                "city_cn": "时序环城",
                "s_name_cn": loop_stations[0][0],
                "e_name_cn": loop_stations[0][0],
                "s_stop_id": "timeline-loop-1",
                "e_stop_id": "timeline-loop-1",
                "geometry": LineString(
                    [
                        (loop_stations[0][2], loop_stations[0][3]),
                        (loop_stations[0][2], loop_stations[0][3]),
                    ]
                ),
            },
            *[
                {
                    "seg_id": f"loop-segment-{sequence}",
                    "seg_seq": sequence,
                    "s_route_id": "timeline-loop",
                    "e_route_id": "timeline-loop",
                    "route_cn": "时序环线",
                    "city_code": "320",
                    "city_cn": "时序环城",
                    "s_name_cn": start[0],
                    "e_name_cn": end[0],
                    "s_stop_id": f"timeline-loop-{sequence}",
                    "e_stop_id": f"timeline-loop-{(sequence % 4) + 1}",
                    "geometry": LineString([(start[2], start[3]), (end[2], end[3])]),
                }
                for sequence, (start, end) in enumerate(
                    zip(
                        loop_stations,
                        (*loop_stations[1:], loop_stations[0]),
                        strict=True,
                    ),
                    start=1,
                )
            ],
        ],
        geometry="geometry",
        crs="EPSG:4326",
    )
    routes.to_file(root / "metro_routes.shp", encoding="UTF-8")
    stations.to_file(root / "metro_stations_timeline.shp", encoding="UTF-8")
    segments.to_file(root / "metro_routes_segment_timeline.shp", encoding="UTF-8")


def test_imports_sciencedb_timeline_bundle_and_reconstructs_stop_order(
    tmp_path,
    db: Session,  # type: ignore[no-untyped-def]
) -> None:
    from app.importers.cptond import (
        IMPORTER_SCHEMA_VERSION,
        SCIENCEDB_TIMELINE_LICENSE,
        SCIENCEDB_TIMELINE_SOURCE_URL,
        TIMELINE_FORMAT,
        audit_dataset,
        create_dataset_import,
        run_dataset_import,
    )

    _write_sciencedb_timeline_bundle(tmp_path)
    audit = audit_dataset(tmp_path)
    assert audit.source_format == TIMELINE_FORMAT
    assert audit.source_url == SCIENCEDB_TIMELINE_SOURCE_URL
    assert audit.license == SCIENCEDB_TIMELINE_LICENSE
    assert audit.default_source_version == "timeline-v1"
    assert audit.route_count == 2
    assert audit.stop_count == 7
    assert audit.bundles[0].segments_path is not None

    handle = create_dataset_import(audit, "timeline-v1")
    run_dataset_import(handle.import_id, audit)
    db.expire_all()

    dataset = db.get(DatasetVersion, handle.import_id)
    assert dataset is not None
    assert dataset.status == "ready"
    assert dataset.source_url == SCIENCEDB_TIMELINE_SOURCE_URL
    assert dataset.license == SCIENCEDB_TIMELINE_LICENSE
    assert dataset.importer_schema_version == IMPORTER_SCHEMA_VERSION
    assert dataset.total_cities == 2
    assert dataset.ready_lines == 2

    variant = db.scalar(
        select(RouteVariant).where(
            RouteVariant.dataset_version_id == handle.import_id,
            RouteVariant.source_route_id == "310:timeline-1",
        )
    )
    assert variant is not None
    assert variant.source_route_id == "310:timeline-1"
    assert variant.direction_name == "起点 → 终点"
    station_names = db.scalars(
        select(Station.name_cn)
        .join(RouteStop, RouteStop.station_id == Station.id)
        .where(RouteStop.route_variant_id == variant.id)
        .order_by(RouteStop.source_sequence)
    ).all()
    assert station_names == ["起点", "中点", "终点"]
    loop_variant = db.scalar(
        select(RouteVariant).where(
            RouteVariant.dataset_version_id == handle.import_id,
            RouteVariant.source_route_id == "320:timeline-loop",
        )
    )
    assert loop_variant is not None
    assert loop_variant.is_loop is True
    assert loop_variant.direction_name == "东 → 东"


def test_imports_official_field_contract_and_marks_branches(
    tmp_path,
    db: Session,  # type: ignore[no-untyped-def]
) -> None:
    from app.importers.cptond import (
        audit_dataset,
        create_dataset_import,
        run_dataset_import,
    )

    previous = seed_linear_network(db)
    _write_city_bundle(
        tmp_path,
        slug="linear",
        city_code="100",
        city_name="直线城",
        routes=[
            {
                "route_id": "linear-1",
                "route_cn": "1号线",
                "route_en": "Line 1",
                "city_code": "100",
                "city_cn": "直线城",
                "city_en": "Linear City",
                "loop": 0,
                "start_stop": "甲",
                "end_stop": "丙",
                "geometry": LineString([(110.0, 30.0), (110.05, 30.0), (110.1, 30.0)]),
            }
        ],
        stops=[
            {
                "stop_id": f"linear-{sequence}",
                "name_cn": name,
                "name_en": name,
                "route_id": "linear-1",
                "route_cn": "1号线",
                "city_code": "100",
                "city_cn": "直线城",
                "city_en": "Linear City",
                "sequence": sequence,
                "geometry": Point(lon, 30.0),
            }
            for sequence, (name, lon) in enumerate(
                (("甲", 110.0), ("乙", 110.05), ("丙", 110.1)), start=1
            )
        ],
    )
    loop_coordinates = [
        (116.0, 39.0),
        (116.04, 39.0),
        (116.04, 39.04),
        (116.0, 39.04),
        (116.0, 39.0),
    ]
    _write_city_bundle(
        tmp_path,
        slug="branch",
        city_code="200",
        city_name="环支城",
        routes=[
            {
                "route_id": "loop-1",
                "route_cn": "环线",
                "route_en": "Loop",
                "city_code": "200",
                "city_cn": "环支城",
                "city_en": "Loop City",
                "loop": 1,
                "start_stop": "东",
                "end_stop": "东",
                "geometry": LineString(loop_coordinates),
            },
            {
                "route_id": "branch-1",
                "route_cn": "支线",
                "route_en": "Branch",
                "city_code": "200",
                "city_cn": "环支城",
                "city_en": "Loop City",
                "loop": 0,
                "start_stop": "东",
                "end_stop": "北",
                "geometry": LineString(
                    [(116.0, 39.0), (116.04, 39.0), (116.04, 39.04)]
                ),
            },
            {
                "route_id": "branch-2",
                "route_cn": "支线",
                "route_en": "Branch",
                "city_code": "200",
                "city_cn": "环支城",
                "city_en": "Loop City",
                "loop": 0,
                "start_stop": "东",
                "end_stop": "西",
                "geometry": LineString([(116.0, 39.0), (116.04, 39.0), (116.0, 39.04)]),
            },
        ],
        stops=[
            *[
                {
                    "stop_id": f"loop-{sequence}",
                    "name_cn": name,
                    "name_en": name,
                    "route_id": "loop-1",
                    "route_cn": "环线",
                    "city_code": "200",
                    "city_cn": "环支城",
                    "city_en": "Loop City",
                    "sequence": sequence,
                    "geometry": Point(lon, lat),
                }
                for sequence, (name, lon, lat) in enumerate(
                    (
                        ("东", 116.0, 39.0),
                        ("南", 116.04, 39.0),
                        ("北", 116.04, 39.04),
                        ("西", 116.0, 39.04),
                    ),
                    start=1,
                )
            ],
            *[
                {
                    "stop_id": f"{route_id}-{sequence}",
                    "name_cn": name,
                    "name_en": name,
                    "route_id": route_id,
                    "route_cn": "支线",
                    "city_code": "200",
                    "city_cn": "环支城",
                    "city_en": "Loop City",
                    "sequence": sequence,
                    "geometry": Point(lon, lat),
                }
                for route_id, destination in (
                    ("branch-1", ("北", 116.04, 39.04)),
                    ("branch-2", ("西", 116.0, 39.04)),
                )
                for sequence, (name, lon, lat) in enumerate(
                    (("东", 116.0, 39.0), ("南", 116.04, 39.0), destination),
                    start=1,
                )
            ],
        ],
    )

    audit = audit_dataset(tmp_path)
    assert audit.route_count == 4
    assert audit.stop_count == 13
    handle = create_dataset_import(audit, "contract-test")
    assert handle.status == "staging"
    assert handle.should_run is True
    run_dataset_import(handle.import_id, audit)
    db.expire_all()
    dataset = db.get(DatasetVersion, handle.import_id)
    assert dataset is not None and dataset.status == "ready"
    assert dataset.total_cities == 2
    assert dataset.processed_cities == 2
    assert dataset.route_count == 4
    assert dataset.stop_count == 13
    assert dataset.ready_lines == 3
    assert dataset.blocked_lines == 0
    assert dataset.completed_at is not None
    previous_dataset = db.get(DatasetVersion, previous.dataset_id)
    assert previous_dataset is not None and previous_dataset.status == "retired"
    cities = db.scalars(
        select(City)
        .where(City.dataset_version_id == handle.import_id)
        .order_by(City.name_cn)
    ).all()
    assert {city.name_cn for city in cities} == {"直线城", "环支城"}
    branch_variants = db.scalars(
        select(RouteVariant).where(
            RouteVariant.dataset_version_id == handle.import_id,
            RouteVariant.source_route_id.in_(["200:branch-1", "200:branch-2"]),
        )
    ).all()
    assert len(branch_variants) == 2
    assert all(variant.is_branch for variant in branch_variants)


def test_unexpected_import_failure_cleans_staging_rows_and_records_error(
    tmp_path,
    db: Session,  # type: ignore[no-untyped-def]
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from app.importers import cptond

    _write_minimal_linear_bundle(tmp_path)
    audit = cptond.audit_dataset(tmp_path)
    handle = cptond.create_dataset_import(audit, "failure-test")

    def fail_after_partial_commit(
        import_db: Session, dataset: DatasetVersion, audit_argument: object
    ) -> None:
        del audit_argument
        dataset.status = "checking"
        import_db.add(
            City(
                dataset_version_id=dataset.id,
                source_city_code="partial",
                name_cn="半成品",
                name_en=None,
                center_lon=110,
                center_lat=30,
                min_lon=109,
                min_lat=29,
                max_lon=111,
                max_lat=31,
                status="checking",
            )
        )
        import_db.commit()
        raise RuntimeError("synthetic importer failure")

    monkeypatch.setattr(cptond, "_import_into_session", fail_after_partial_commit)
    cptond.run_dataset_import(handle.import_id, audit)
    db.expire_all()
    dataset = db.get(DatasetVersion, handle.import_id)
    assert dataset is not None
    assert dataset.status == "failed"
    assert dataset.error_code == "unexpected_import_error"
    assert dataset.error_message == "synthetic importer failure"
    assert dataset.completed_at is not None
    assert (
        db.scalar(
            select(City).where(City.dataset_version_id == handle.import_id).limit(1)
        )
        is None
    )


def test_staging_import_can_be_cancelled_after_page_reload(
    tmp_path,
    client,  # type: ignore[no-untyped-def]
    db: Session,
) -> None:
    from app.importers.cptond import audit_dataset, create_dataset_import

    seed_linear_network(db)
    _write_minimal_linear_bundle(tmp_path)
    audit = audit_dataset(tmp_path)
    handle = create_dataset_import(audit, "cancel-test")

    status_response = client.get("/api/v1/data/status")
    assert status_response.status_code == 200
    assert status_response.json()["import_id"] == handle.import_id
    assert status_response.json()["status"] == "importing"
    assert status_response.json()["ready_available"] is True

    cancel_response = client.post(f"/api/v1/data/imports/{handle.import_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    db.expire_all()
    dataset = db.get(DatasetVersion, handle.import_id)
    assert dataset is not None
    assert dataset.status == "cancelled"
    assert dataset.error_code == "import_cancelled"
    cancelled_status = client.get("/api/v1/data/status").json()
    assert cancelled_status["status"] == "cancelled"
    assert cancelled_status["ready_available"] is True
