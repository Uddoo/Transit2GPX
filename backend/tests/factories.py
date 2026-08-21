from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString
from sqlalchemy.orm import Session

from app.db.models import (
    City,
    DatasetVersion,
    Line,
    RouteEdge,
    RouteStop,
    RouteVariant,
    Station,
)
from app.matching.names import normalize_line_name, normalize_station_name, pinyin_keys


@dataclass(frozen=True, slots=True)
class LinearNetwork:
    dataset_id: int
    city_id: int
    line_id: int
    variant_id: int
    station_ids: tuple[int, ...]
    edge_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class TransferNetwork:
    city_id: int
    first_line_id: int
    second_line_id: int
    start_station_id: int
    transfer_station_id: int
    end_station_id: int
    edge_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LoopNetwork:
    city_id: int
    line_id: int
    station_ids: tuple[int, ...]
    edge_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class BranchNetwork:
    city_id: int
    line_id: int
    start_station_id: int
    shared_station_id: int
    first_end_station_id: int
    second_end_station_id: int


def seed_linear_network(
    db: Session,
    *,
    suffix: str = "",
    city_name: str = "上海",
    city_code: str = "310000",
    line_name: str = "测试线",
    start_lon: float = 121.40,
) -> LinearNetwork:
    dataset = DatasetVersion(
        source_name="CPTOND",
        source_version=f"test-v2{suffix}",
        captured_at="2025-06",
        license="CC BY 4.0",
        source_url="https://doi.org/10.6084/m9.figshare.29377427",
        checksum=f"linear-network{suffix}",
        importer_schema_version="test",
        status="ready",
    )
    db.add(dataset)
    db.flush()
    city = City(
        dataset_version_id=dataset.id,
        source_city_code=city_code,
        name_cn=city_name,
        name_en=f"Test City {suffix}" if suffix else "Shanghai",
        center_lon=start_lon + 0.05,
        center_lat=31.20,
        min_lon=start_lon,
        min_lat=31.18,
        max_lon=start_lon + 0.10,
        max_lat=31.22,
        status="ready",
    )
    db.add(city)
    db.flush()
    line = Line(
        city_id=city.id,
        name_cn=line_name,
        name_en=f"Test Line {suffix}" if suffix else "Test Line",
        normalized_name=normalize_line_name(line_name),
        display_color="#079aa4",
        sort_order=1,
        status="ready",
    )
    db.add(line)
    db.flush()
    coordinates = [
        (start_lon, 31.20),
        (start_lon + 0.05, 31.20),
        (start_lon + 0.10, 31.20),
    ]
    variant = RouteVariant(
        line_id=line.id,
        dataset_version_id=dataset.id,
        source_route_id=f"test{suffix}:forward",
        source_route_name=line_name,
        direction_name="正向",
        is_loop=False,
        is_branch=False,
        geometry_wkb=LineString(coordinates).wkb,
        match_method="test",
        quality_status="ready",
        quality_flags_json=[],
    )
    db.add(variant)
    db.flush()
    stations: list[Station] = []
    route_stops: list[RouteStop] = []
    for sequence, (name, coordinate) in enumerate(
        zip(
            (f"甲站{suffix}", f"乙站{suffix}", f"丙站{suffix}"),
            coordinates,
            strict=True,
        ),
        start=1,
    ):
        full, initials = pinyin_keys(name)
        station = Station(
            city_id=city.id,
            name_cn=name,
            name_en=None,
            normalized_name=normalize_station_name(name),
            pinyin_full=full,
            pinyin_initials=initials,
            lon=coordinate[0],
            lat=coordinate[1],
            cluster_no=0,
        )
        db.add(station)
        db.flush()
        stop = RouteStop(
            route_variant_id=variant.id,
            station_id=station.id,
            source_stop_id=f"stop-{sequence}",
            source_sequence=sequence,
            source_lon=coordinate[0],
            source_lat=coordinate[1],
            projected_measure_m=(sequence - 1) * 5000,
            projection_error_m=0,
            match_quality="test",
        )
        db.add(stop)
        db.flush()
        stations.append(station)
        route_stops.append(stop)
    edge_ids: list[int] = []
    for index in range(2):
        geometry = LineString(coordinates[index : index + 2])
        edge = RouteEdge(
            route_variant_id=variant.id,
            from_route_stop_id=route_stops[index].id,
            to_route_stop_id=route_stops[index + 1].id,
            from_station_id=stations[index].id,
            to_station_id=stations[index + 1].id,
            sequence_from=index + 1,
            sequence_to=index + 2,
            distance_m=4800,
            geometry_wkb=geometry.wkb,
            min_lon=geometry.bounds[0],
            min_lat=geometry.bounds[1],
            max_lon=geometry.bounds[2],
            max_lat=geometry.bounds[3],
            quality_status="ready",
            quality_flags_json=[],
        )
        db.add(edge)
        db.flush()
        edge_ids.append(edge.id)
    db.commit()
    return LinearNetwork(
        dataset_id=dataset.id,
        city_id=city.id,
        line_id=line.id,
        variant_id=variant.id,
        station_ids=tuple(station.id for station in stations),
        edge_ids=tuple(edge_ids),
    )


def seed_transfer_network(db: Session) -> TransferNetwork:
    first = seed_linear_network(db)
    second_line = Line(
        city_id=first.city_id,
        name_cn="换乘测试线",
        name_en="Transfer Test Line",
        normalized_name=normalize_line_name("换乘测试线"),
        display_color="#da5b3c",
        sort_order=2,
        status="ready",
    )
    db.add(second_line)
    db.flush()
    coordinates = [(121.50, 31.20), (121.55, 31.22), (121.60, 31.24)]
    variant = RouteVariant(
        line_id=second_line.id,
        dataset_version_id=first.dataset_id,
        source_route_id="transfer:forward",
        source_route_name=second_line.name_cn,
        direction_name="正向",
        is_loop=False,
        is_branch=False,
        geometry_wkb=LineString(coordinates).wkb,
        match_method="test",
        quality_status="ready",
        quality_flags_json=[],
    )
    db.add(variant)
    db.flush()
    transfer_station = db.get(Station, first.station_ids[-1])
    assert transfer_station is not None
    stations = [transfer_station]
    for name, (lon, lat) in zip(("丁站", "戊站"), coordinates[1:], strict=True):
        full, initials = pinyin_keys(name)
        station = Station(
            city_id=first.city_id,
            name_cn=name,
            name_en=None,
            normalized_name=normalize_station_name(name),
            pinyin_full=full,
            pinyin_initials=initials,
            lon=lon,
            lat=lat,
            cluster_no=0,
        )
        db.add(station)
        db.flush()
        stations.append(station)
    route_stops: list[RouteStop] = []
    for sequence, (station, coordinate) in enumerate(
        zip(stations, coordinates, strict=True), start=1
    ):
        stop = RouteStop(
            route_variant_id=variant.id,
            station_id=station.id,
            source_stop_id=f"transfer-{sequence}",
            source_sequence=sequence,
            source_lon=coordinate[0],
            source_lat=coordinate[1],
            projected_measure_m=(sequence - 1) * 5000,
            projection_error_m=0,
            match_quality="test",
        )
        db.add(stop)
        db.flush()
        route_stops.append(stop)
    second_edge_ids: list[int] = []
    for index in range(2):
        geometry = LineString(coordinates[index : index + 2])
        edge = RouteEdge(
            route_variant_id=variant.id,
            from_route_stop_id=route_stops[index].id,
            to_route_stop_id=route_stops[index + 1].id,
            from_station_id=stations[index].id,
            to_station_id=stations[index + 1].id,
            sequence_from=index + 1,
            sequence_to=index + 2,
            distance_m=5200,
            geometry_wkb=geometry.wkb,
            min_lon=geometry.bounds[0],
            min_lat=geometry.bounds[1],
            max_lon=geometry.bounds[2],
            max_lat=geometry.bounds[3],
            quality_status="ready",
            quality_flags_json=[],
        )
        db.add(edge)
        db.flush()
        second_edge_ids.append(edge.id)
    db.commit()
    return TransferNetwork(
        city_id=first.city_id,
        first_line_id=first.line_id,
        second_line_id=second_line.id,
        start_station_id=first.station_ids[0],
        transfer_station_id=first.station_ids[-1],
        end_station_id=stations[-1].id,
        edge_ids=(*first.edge_ids, *second_edge_ids),
    )


def seed_loop_network(db: Session) -> LoopNetwork:
    base = seed_linear_network(db)
    line = Line(
        city_id=base.city_id,
        name_cn="测试环线",
        name_en="Test Loop",
        normalized_name=normalize_line_name("测试环线"),
        display_color="#7b5db5",
        sort_order=2,
        status="ready",
    )
    db.add(line)
    db.flush()
    coordinates = [
        (121.60, 31.20),
        (121.64, 31.20),
        (121.64, 31.24),
        (121.60, 31.24),
    ]
    variant = RouteVariant(
        line_id=line.id,
        dataset_version_id=base.dataset_id,
        source_route_id="loop:test",
        source_route_name=line.name_cn,
        direction_name="环线源顺序",
        is_loop=True,
        is_branch=False,
        geometry_wkb=LineString([*coordinates, coordinates[0]]).wkb,
        match_method="test",
        quality_status="ready",
        quality_flags_json=[],
    )
    db.add(variant)
    db.flush()
    stations: list[Station] = []
    stops: list[RouteStop] = []
    for sequence, (name, coordinate) in enumerate(
        zip(("东站", "南站", "西站", "北站"), coordinates, strict=True), start=1
    ):
        full, initials = pinyin_keys(name)
        station = Station(
            city_id=base.city_id,
            name_cn=name,
            name_en=None,
            normalized_name=normalize_station_name(name),
            pinyin_full=full,
            pinyin_initials=initials,
            lon=coordinate[0],
            lat=coordinate[1],
            cluster_no=0,
        )
        db.add(station)
        db.flush()
        stop = RouteStop(
            route_variant_id=variant.id,
            station_id=station.id,
            source_stop_id=f"loop-{sequence}",
            source_sequence=sequence,
            source_lon=coordinate[0],
            source_lat=coordinate[1],
            projected_measure_m=(sequence - 1) * 4000,
            projection_error_m=0,
            match_quality="test",
        )
        db.add(stop)
        db.flush()
        stations.append(station)
        stops.append(stop)
    edge_ids: list[int] = []
    for index in range(4):
        next_index = (index + 1) % 4
        geometry = LineString([coordinates[index], coordinates[next_index]])
        edge = RouteEdge(
            route_variant_id=variant.id,
            from_route_stop_id=stops[index].id,
            to_route_stop_id=stops[next_index].id,
            from_station_id=stations[index].id,
            to_station_id=stations[next_index].id,
            sequence_from=index + 1,
            sequence_to=next_index + 1,
            distance_m=4000,
            geometry_wkb=geometry.wkb,
            min_lon=geometry.bounds[0],
            min_lat=geometry.bounds[1],
            max_lon=geometry.bounds[2],
            max_lat=geometry.bounds[3],
            quality_status="ready",
            quality_flags_json=[],
        )
        db.add(edge)
        db.flush()
        edge_ids.append(edge.id)
    db.commit()
    return LoopNetwork(
        city_id=base.city_id,
        line_id=line.id,
        station_ids=tuple(station.id for station in stations),
        edge_ids=tuple(edge_ids),
    )


def seed_branch_network(db: Session) -> BranchNetwork:
    base = seed_linear_network(db)
    line = Line(
        city_id=base.city_id,
        name_cn="测试支线",
        name_en="Test Branch",
        normalized_name=normalize_line_name("测试支线"),
        display_color="#d17b17",
        sort_order=2,
        status="ready",
    )
    db.add(line)
    db.flush()
    start = db.get(Station, base.station_ids[0])
    shared = db.get(Station, base.station_ids[1])
    first_end = db.get(Station, base.station_ids[2])
    assert start is not None and shared is not None and first_end is not None
    full, initials = pinyin_keys("支线终点")
    second_end = Station(
        city_id=base.city_id,
        name_cn="支线终点",
        name_en=None,
        normalized_name=normalize_station_name("支线终点"),
        pinyin_full=full,
        pinyin_initials=initials,
        lon=121.48,
        lat=31.25,
        cluster_no=0,
    )
    db.add(second_end)
    db.flush()
    for suffix, stations in (
        ("main", [start, shared, first_end]),
        ("branch", [start, shared, second_end]),
    ):
        coordinates = [(station.lon, station.lat) for station in stations]
        variant = RouteVariant(
            line_id=line.id,
            dataset_version_id=base.dataset_id,
            source_route_id=f"branch:{suffix}",
            source_route_name=line.name_cn,
            direction_name=suffix,
            is_loop=False,
            is_branch=True,
            geometry_wkb=LineString(coordinates).wkb,
            match_method="test",
            quality_status="ready",
            quality_flags_json=[],
        )
        db.add(variant)
        db.flush()
        stops: list[RouteStop] = []
        for sequence, station in enumerate(stations, start=1):
            stop = RouteStop(
                route_variant_id=variant.id,
                station_id=station.id,
                source_stop_id=f"{suffix}-{sequence}",
                source_sequence=sequence,
                source_lon=station.lon,
                source_lat=station.lat,
                projected_measure_m=(sequence - 1) * 5000,
                projection_error_m=0,
                match_quality="test",
            )
            db.add(stop)
            db.flush()
            stops.append(stop)
        for index in range(2):
            geometry = LineString(coordinates[index : index + 2])
            db.add(
                RouteEdge(
                    route_variant_id=variant.id,
                    from_route_stop_id=stops[index].id,
                    to_route_stop_id=stops[index + 1].id,
                    from_station_id=stations[index].id,
                    to_station_id=stations[index + 1].id,
                    sequence_from=index + 1,
                    sequence_to=index + 2,
                    distance_m=5000,
                    geometry_wkb=geometry.wkb,
                    min_lon=geometry.bounds[0],
                    min_lat=geometry.bounds[1],
                    max_lon=geometry.bounds[2],
                    max_lat=geometry.bounds[3],
                    quality_status="ready",
                    quality_flags_json=[],
                )
            )
    db.commit()
    return BranchNetwork(
        city_id=base.city_id,
        line_id=line.id,
        start_station_id=start.id,
        shared_station_id=shared.id,
        first_end_station_id=first_end.id,
        second_end_station_id=second_end.id,
    )
