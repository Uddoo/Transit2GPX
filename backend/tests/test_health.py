from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_healthcheck_reports_database(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "database": "ok",
    }
    assert response.headers["x-request-id"].startswith("req_")


def test_data_status_distinguishes_unconfigured_install(client: TestClient) -> None:
    response = client.get("/api/v1/data/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_configured",
        "ready_available": False,
        "import_id": None,
        "dataset": None,
        "captured_at": None,
        "license": None,
        "source_url": None,
        "checksum": None,
        "importer_schema_version": None,
        "cities": 0,
        "route_count": 0,
        "stop_count": 0,
        "total_cities": 0,
        "processed_cities": 0,
        "ready_lines": 0,
        "blocked_lines": 0,
        "imported_at": None,
        "completed_at": None,
        "error_code": None,
        "error_message": None,
        "quality_status": "not_available",
    }


def test_public_config_exposes_switchable_map_provider(client: TestClient) -> None:
    response = client.get("/api/v1/config/public")

    assert response.status_code == 200
    assert response.json() == {
        "map": {
            "tiles_enabled": True,
            "tile_url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "tile_attribution": (
                '&copy; <a href="https://www.openstreetmap.org/copyright">'
                "OpenStreetMap</a> contributors"
            ),
            "max_zoom": 19,
            "external_tiles": True,
        }
    }


def test_map_fails_instead_of_returning_synthetic_geometry(client: TestClient) -> None:
    response = client.get("/api/v1/cities/1/map?line_id=2")

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "dataset_not_ready"
    assert body["details"] == {"city_id": 1}
    assert body["request_id"].startswith("req_")


def test_import_rejects_directory_without_cptond_files(client: TestClient) -> None:
    response = client.post(
        "/api/v1/data/imports",
        json={"directory": "/definitely/not/a/cptond/directory"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "data_directory_not_found"


def test_spa_static_files_support_deep_links_without_masking_assets(
    client: TestClient,
    tmp_path: Path,
) -> None:
    del client
    from app.main import SPAStaticFiles

    (tmp_path / "index.html").write_text("<main>Transit2Fog</main>", encoding="utf-8")
    (tmp_path / "app.js").write_text("export {};", encoding="utf-8")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=tmp_path, html=True), name="frontend")

    with TestClient(app) as spa_client:
        deep_link = spa_client.get("/journeys/new")
        asset = spa_client.get("/app.js")
        missing_asset = spa_client.get("/missing.js")

    assert deep_link.status_code == 200
    assert deep_link.text == "<main>Transit2Fog</main>"
    assert asset.status_code == 200
    assert asset.text == "export {};"
    assert missing_asset.status_code == 404
