from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from factories import (
    seed_branch_network,
    seed_linear_network,
    seed_loop_network,
    seed_transfer_network,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import City, DatasetVersion, Line, RouteEdge, Station
from app.importers.city_pack import (
    CityPackError,
    export_city_pack,
    install_city_pack,
    read_city_pack,
)


def rewrite(path: Path, change, *, checksum: bool = True) -> None:
    with zipfile.ZipFile(path) as source:
        manifest = json.loads(source.read("manifest.json"))
        network = json.loads(source.read("network.json"))
    change(network)
    content = json.dumps(network).encode()
    if checksum:
        manifest["network_sha256"] = hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        target.writestr("manifest.json", json.dumps(manifest))
        target.writestr("network.json", content)


@pytest.mark.parametrize(
    "seed",
    [
        seed_linear_network,
        seed_loop_network,
        seed_branch_network,
        seed_transfer_network,
    ],
)
def test_roundtrip_preserves_network_geometry_and_is_idempotent(
    db: Session, tmp_path: Path, seed
) -> None:
    original = seed(db)
    path = tmp_path / "city.t2fcity"
    preview = export_city_pack(db, original.city_id, path, "Test source attribution")
    first_bytes = path.read_bytes()
    export_city_pack(db, original.city_id, path, "Test source attribution")
    assert path.read_bytes() == first_bytes
    _, before = read_city_pack(path)
    installed = install_city_pack(db, path, preview.package_id)
    assert install_city_pack(db, path, preview.package_id) == installed
    city = db.scalar(select(City).where(City.dataset_version_id == installed))
    assert city is not None and city.id != original.city_id
    second = tmp_path / "again.t2fcity"
    export_city_pack(db, city.id, second, "Must preserve original attribution")
    again, after = read_city_pack(second)
    assert again.manifest.source == preview.manifest.source
    for table in before:
        assert len(before[table]) == len(after[table])
    assert [row["geometry_wkb"] for row in before["edges"]] == [
        row["geometry_wkb"] for row in after["edges"]
    ]


def test_pack_upload_install_path_save_export_and_update_keep_history(
    client: TestClient, db: Session, tmp_path: Path
) -> None:
    from test_journey_export_api import _leg_input, _path_candidate

    original = seed_linear_network(db)
    other = seed_linear_network(
        db, suffix="other", city_code="330100", city_name="杭州"
    )
    path = tmp_path / "shanghai.t2fcity"
    export_city_pack(db, original.city_id, path, "CPTOND test fixture / CC BY 4.0")
    response = client.post(
        "/api/v1/data/city-packs/inspect",
        files={"file": (path.name, path.read_bytes())},
    )
    assert response.status_code == 200, response.text
    package_id = response.json()["package_id"]
    result = client.post(
        "/api/v1/data/city-packs/install", json={"package_id": package_id}
    )
    assert result.status_code == 200, result.text
    cities = client.get("/api/v1/cities").json()
    assert len(cities) == 2
    city_id = next(row["id"] for row in cities if row["name_cn"] == "上海")
    assert city_id != original.city_id and other.city_id in {
        row["id"] for row in cities
    }
    line = db.scalar(select(Line).where(Line.city_id == city_id))
    stations = db.scalars(
        select(Station).where(Station.city_id == city_id).order_by(Station.id)
    ).all()
    assert line is not None
    ids = dict(
        city_id=city_id,
        line_id=line.id,
        start_station_id=stations[0].id,
        end_station_id=stations[-1].id,
    )
    candidate = _path_candidate(client, **ids)
    response = client.post(
        "/api/v1/journeys",
        json={
            "journey_code": "citypack-trip",
            "source_type": "manual",
            "legs": [_leg_input(**ids, candidate=candidate)],
        },
    )
    assert response.status_code == 201, response.text
    journey_id = response.json()["id"]
    # A new package version supersedes just Shanghai, retaining old edge objects.
    old_geometry = {
        edge.id: edge.geometry_wkb for edge in db.scalars(select(RouteEdge))
    }
    rewrite(path, lambda network: network["lines"][0].update(display_color="#123456"))
    updated = read_city_pack(path)[0]
    install_city_pack(db, path, updated.package_id)
    assert all(
        db.get(RouteEdge, key).geometry_wkb == geometry
        for key, geometry in old_geometry.items()
    )
    cities = client.get("/api/v1/cities").json()
    assert len(cities) == 2 and other.city_id in {row["id"] for row in cities}
    request = {
        "mode": "journeys",
        "max_segment_length_m": 25,
        "journey_ids": [journey_id],
    }
    preview = client.post("/api/v1/exports/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert preview.json()["blocking_errors"] == []
    exported = client.post(
        "/api/v1/exports/gpx",
        json={**request, "preview_token": preview.json()["preview_token"]},
    )
    assert exported.status_code == 200 and b"trkpt" in exported.content


@pytest.mark.parametrize(
    "change",
    [
        lambda n: n["edges"][0].update(from_station_id=999999),
        lambda n: n["edges"][0].update(sequence_from=99),
        lambda n: n["edges"][0].update(geometry_wkb="bad"),
        lambda n: n["edges"][0].update(min_lon=0),
        lambda n: n["stations"][0].update(lon=200),
        lambda n: n["cities"][0].update(status="checking"),
        lambda n: n["lines"][0].update(extra="bad"),
        lambda n: n["stations"].append(n["stations"][0]),
        lambda n: n["edges"].clear(),
        lambda n: n["edges"].pop(),
    ],
)
def test_invalid_package_cannot_change_existing_data(
    db: Session, tmp_path: Path, change
) -> None:
    original = seed_linear_network(db)
    path = tmp_path / "bad.t2fcity"
    export_city_pack(db, original.city_id, path, "fixture")
    rewrite(path, change)
    with pytest.raises(CityPackError):
        read_city_pack(path)
    assert db.scalar(select(func.count()).select_from(DatasetVersion)) == 1


def test_checksum_extra_entries_and_transaction_failure_preserve_data(
    client: TestClient, db: Session, tmp_path: Path
) -> None:
    original = seed_linear_network(db)
    path = tmp_path / "bad.t2fcity"
    preview = export_city_pack(db, original.city_id, path, "fixture")
    with pytest.raises(CityPackError, match="预览后"):
        install_city_pack(db, path, "0" * 64)
    rewrite(path, lambda n: n["lines"][0].update(name_cn="changed"), checksum=False)
    assert (
        client.post(
            "/api/v1/data/city-packs/inspect",
            files={"file": ("bad.t2fcity", path.read_bytes())},
        ).status_code
        == 422
    )
    export_city_pack(db, original.city_id, path, "fixture")
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("../escape", "bad")
    with pytest.raises(CityPackError):
        read_city_pack(path)
    export_city_pack(db, original.city_id, path, "fixture")
    # Duplicate a unique station identity under another local ID. Database
    # validation occurs after inserting some records, so rollback is essential.
    rewrite(path, lambda n: n["stations"].append({**n["stations"][0], "id": 999}))
    response = client.post(
        "/api/v1/data/city-packs/inspect",
        files={"file": ("duplicate.t2fcity", path.read_bytes())},
    )
    assert response.status_code == 200
    response = client.post(
        "/api/v1/data/city-packs/install",
        json={"package_id": response.json()["package_id"]},
    )
    assert response.status_code == 422
    assert db.scalar(select(func.count()).select_from(DatasetVersion)) == 1
    assert db.get(City, original.city_id).status == "ready"
    assert (
        client.post(
            "/api/v1/data/city-packs/install", json={"package_id": "../escape"}
        ).status_code
        == 422
    )
    assert preview.manifest.source.license == "CC BY 4.0"


def test_base_import_graph_does_not_load_heavy_packages() -> None:
    code = """
import importlib.abc, sys
class NoHeavy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'geopandas','pandas','pyogrio'}:
            raise AssertionError('Unexpected heavy import: '+fullname)
sys.meta_path.insert(0, NoHeavy())
from app.main import create_app
from app.importers.city_pack import read_city_pack
from app.rail.osm_reader import read_station_records
assert create_app().routes
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
