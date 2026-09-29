from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rail_validate_routes.py"
spec = importlib.util.spec_from_file_location("rail_acceptance_security", SCRIPT)
assert spec is not None and spec.loader is not None
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.fixture
def sidecar() -> Iterator[tuple[str, list[str]]]:
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            if self.path == "/transit2fog/metadata":
                self.send_error(404)
                return
            if self.path == "/route":
                self.send_response(302)
                self.send_header("Location", "/info")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://localhost:{server.server_port}", paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/info",
        "http://example.com/info",
        "file:///etc/passwd",
        "http://127.0.0.1.evil/info",
        "http://user@127.0.0.1/info",
        "http://127.0.0.1/info#fragment",
        "http://127.0.0.1:99999/info",
        "http://127.0.0.1/private/info",
        "http://127.0.0.1:0/info",
    ],
)
def test_acceptance_rejects_unsafe_destinations(url: str) -> None:
    with pytest.raises(ValueError):
        acceptance._json_request(url)


def test_acceptance_ignores_proxies_and_keeps_legacy_fallback(
    sidecar: tuple[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    base, paths = sidecar
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    assert acceptance._json_request(base + "/info") == {"ok": True}
    assert acceptance._sidecar_identity(base) == {"ok": True}
    assert paths == ["/info", "/transit2fog/metadata", "/metro2fog/metadata"]


def test_acceptance_refuses_redirects(sidecar: tuple[str, list[str]]) -> None:
    base, paths = sidecar
    with pytest.raises(HTTPError) as error:
        acceptance._json_request(base + "/route")
    assert error.value.code == 302
    assert paths == ["/route"]
