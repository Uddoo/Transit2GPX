from __future__ import annotations

import json
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

from app import __version__

PROJECT_DIR = Path(__file__).resolve().parents[2]


def test_release_versions_are_aligned() -> None:
    backend = tomllib.loads(
        (PROJECT_DIR / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    frontend = json.loads(
        (PROJECT_DIR / "frontend" / "package.json").read_text(encoding="utf-8")
    )

    assert __version__ == backend["project"]["version"]
    assert __version__ == frontend["version"]
    assert backend["project"]["license"] == "Apache-2.0"
    assert frontend["license"] == "Apache-2.0"
    assert (
        (PROJECT_DIR / "LICENSE")
        .read_text(encoding="utf-8")
        .lstrip()
        .startswith("Apache License\n")
    )
    assert (PROJECT_DIR / "NOTICE").is_file()


def test_openapi_release_metadata(client: TestClient) -> None:
    info = client.app.openapi()["info"]

    assert info["version"] == __version__
    assert info["license"] == {
        "name": "Apache License 2.0",
        "identifier": "Apache-2.0",
    }
