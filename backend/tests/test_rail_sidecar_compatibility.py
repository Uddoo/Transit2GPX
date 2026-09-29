from __future__ import annotations

from typing import Any
from urllib.error import HTTPError

import pytest

from app.rail.sidecar import fetch_sidecar_info


def _info() -> dict[str, Any]:
    return {
        "version": "11.0",
        "profiles": [
            {"name": "china_high_speed"},
            {"name": "china_emu"},
            {"name": "china_conventional"},
        ],
        "bbox": [69.0, 18.0, 135.0, 54.0],
    }


def _identity() -> dict[str, str]:
    return {
        "graph_version": "china-20260815-r3.1",
        "pbf_sha256": "a" * 64,
        "profile_version": "2026-08-21-r0.1",
        "openrailrouting_commit": "c8d4ef1",
    }


def test_sidecar_identity_prefers_transit2gpx_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def fake_fetch(_base_url: str, path: str, _timeout: float) -> Any:
        requested_paths.append(path)
        return _info() if path == "/info" else _identity()

    monkeypatch.setattr("app.rail.sidecar._fetch_json", fake_fetch)

    result = fetch_sidecar_info("http://127.0.0.1:8989", 1.0)

    assert result.graph_version == "china-20260815-r3.1"
    assert requested_paths == ["/info", "/transit2fog/metadata"]


def test_sidecar_identity_falls_back_to_legacy_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def fake_fetch(_base_url: str, path: str, _timeout: float) -> Any:
        requested_paths.append(path)
        if path == "/info":
            return _info()
        if path == "/transit2fog/metadata":
            raise HTTPError(path, 404, "Not Found", None, None)
        return _identity()

    monkeypatch.setattr("app.rail.sidecar._fetch_json", fake_fetch)

    result = fetch_sidecar_info("http://127.0.0.1:8989", 1.0)

    assert result.graph_version == "china-20260815-r3.1"
    assert requested_paths == [
        "/info",
        "/transit2fog/metadata",
        "/metro2fog/metadata",
    ]
