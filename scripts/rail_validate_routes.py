from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

EXPECTED_PROFILES = {
    "china_high_speed",
    "china_emu",
    "china_conventional",
}


def _json_request(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Transit2Fog/rail-acceptance",
        },
    )
    with urlopen(request, timeout=30) as response:
        payload: Any = json.load(response)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected an object response from {url}")
    return payload


def _sidecar_identity(base_url: str) -> dict[str, Any]:
    try:
        return _json_request(f"{base_url}/transit2fog/metadata")
    except HTTPError as error:
        if error.code != 404:
            raise
        return _json_request(f"{base_url}/metro2fog/metadata")


def _haversine_m(first: list[float], second: dict[str, Any]) -> float:
    lon1, lat1 = map(math.radians, first[:2])
    lon2 = math.radians(float(second["lon"]))
    lat2 = math.radians(float(second["lat"]))
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 6_371_008.8 * 2 * math.asin(math.sqrt(value))


def _validate_way_ranges(ranges: object, coordinate_count: int) -> int:
    if not isinstance(ranges, list) or not ranges:
        raise RuntimeError("Route response does not include OSM way ranges.")
    expected_start = 0
    unique_way_ids: set[int] = set()
    for item in ranges:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not all(isinstance(value, int) for value in item)
        ):
            raise RuntimeError("Route response contains an invalid OSM way range.")
        start_index, end_index, way_id = item
        if start_index != expected_start or end_index <= start_index:
            raise RuntimeError("OSM way ranges are not continuous and ordered.")
        expected_start = end_index
        unique_way_ids.add(way_id)
    if expected_start != coordinate_count - 1:
        raise RuntimeError("OSM way ranges do not cover the complete route geometry.")
    return len(unique_way_ids)


def validate_routes(base_url: str, manifest_path: Path) -> dict[str, Any]:
    manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("routes"), list)
        or not manifest["routes"]
    ):
        raise TypeError("Acceptance manifest must contain a routes list.")
    base_url = base_url.rstrip("/")
    info = _json_request(f"{base_url}/info")
    identity = _sidecar_identity(base_url)
    graph_version = manifest.get("graph_version")
    if (
        not isinstance(graph_version, str)
        or identity.get("graph_version") != graph_version
    ):
        raise RuntimeError(
            "Running sidecar graph identity does not match the acceptance manifest."
        )
    profiles = {
        item.get("name") for item in info.get("profiles", []) if isinstance(item, dict)
    }
    if not EXPECTED_PROFILES.issubset(profiles):
        raise RuntimeError(
            "Sidecar is missing one or more required China rail profiles."
        )

    results: list[dict[str, Any]] = []
    for route in manifest["routes"]:
        points = route["points"]
        profile = str(route["profile"])
        parameters: list[tuple[str, str]] = [
            ("point", f"{float(point['lat']):.8f},{float(point['lon']):.8f}")
            for point in points
        ]
        parameters.extend(
            [
                ("profile", profile),
                ("points_encoded", "false"),
                ("instructions", "false"),
                ("details", "osm_way_id"),
                ("details", "max_speed"),
                ("details", "rail_average_speed"),
                ("details", "railway_class"),
                ("details", "railway_service"),
                ("details", "electrified"),
            ]
        )
        started_at = time.perf_counter()
        payload = _json_request(f"{base_url}/route?{urlencode(parameters)}")
        query_latency_ms = (time.perf_counter() - started_at) * 1000
        maximum_latency_ms = float(manifest.get("max_query_latency_ms", 5_000))
        if query_latency_ms > maximum_latency_ms:
            raise RuntimeError(
                f"{route['name']}: query took {query_latency_ms:.1f} ms, "
                f"above the {maximum_latency_ms:.1f} ms limit."
            )
        paths = payload.get("paths")
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            raise RuntimeError(f"{route['name']}: sidecar returned no path.")
        path = paths[0]
        geometry = path.get("points")
        details = path.get("details")
        coordinates = (
            geometry.get("coordinates") if isinstance(geometry, dict) else None
        )
        way_ranges = details.get("osm_way_id") if isinstance(details, dict) else None
        if not isinstance(details, dict) or any(
            not isinstance(details.get(name), list) or not details[name]
            for name in (
                "max_speed",
                "rail_average_speed",
                "railway_class",
                "railway_service",
                "electrified",
            )
        ):
            raise RuntimeError(
                f"{route['name']}: scoring attributes are missing from the route."
            )
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise RuntimeError(f"{route['name']}: path geometry is invalid.")
        if not all(
            isinstance(coordinate, list)
            and len(coordinate) >= 2
            and all(isinstance(value, int | float) for value in coordinate[:2])
            for coordinate in coordinates
        ):
            raise RuntimeError(
                f"{route['name']}: path is not valid WGS-84 coordinates."
            )
        distance_m = float(path.get("distance", 0))
        bounds = route["distance_km"]
        if not float(bounds["min"]) * 1000 <= distance_m <= float(bounds["max"]) * 1000:
            raise RuntimeError(
                f"{route['name']}: {distance_m / 1000:.1f} km is outside the expected range."
            )
        start_snap_m = _haversine_m(coordinates[0], points[0])
        end_snap_m = _haversine_m(coordinates[-1], points[-1])
        if max(start_snap_m, end_snap_m) > 2_000:
            raise RuntimeError(f"{route['name']}: station snap exceeds 2 km.")
        unique_way_count = _validate_way_ranges(way_ranges, len(coordinates))
        results.append(
            {
                "name": route["name"],
                "profile": profile,
                "distance_m": distance_m,
                "duration_ms": int(path["time"]),
                "coordinate_count": len(coordinates),
                "unique_osm_way_count": unique_way_count,
                "start_snap_m": round(start_snap_m, 3),
                "end_snap_m": round(end_snap_m, 3),
                "query_latency_ms": round(query_latency_ms, 3),
                "status": "passed",
            }
        )
    latencies = sorted(float(result["query_latency_ms"]) for result in results)
    percentile_95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    return {
        "status": "passed",
        "validated_at": datetime.now(UTC).isoformat(),
        "graph_version": graph_version,
        "sidecar_identity": identity,
        "sidecar_version": info.get("version"),
        "sidecar_bbox": info.get("bbox"),
        "query_latency_ms": {
            "median": round(latencies[len(latencies) // 2], 3),
            "p95": round(latencies[percentile_95_index], 3),
            "max": round(latencies[-1], 3),
        },
        "routes": results,
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate representative China railway routes against a running sidecar."
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8989", help="Loopback sidecar URL."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_routes(args.base_url, args.manifest.resolve())
    if args.output:
        _write_atomic(args.output.resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
