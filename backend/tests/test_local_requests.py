from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.local_requests import LocalRequestMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LocalRequestMiddleware)

    @app.api_route("/sensitive", methods=["GET", "POST"])
    def sensitive() -> dict[str, bool]:
        return {"reached": True}

    return app


@pytest.mark.parametrize(
    "base", ["http://127.0.0.1:8765", "http://localhost:5173", "http://[::1]:8765"]
)
def test_local_cli_and_same_origin_requests_remain_supported(base: str) -> None:
    # TestClient's transport cannot parse bracketed IPv6 URLs; exercise the
    # real Host/Origin headers without changing the test transport's authority.
    with TestClient(
        _app(),
        base_url="http://127.0.0.1:8765",
        headers={"Host": urlsplit(base).netloc},
    ) as client:
        assert client.get("/sensitive").json() == {"reached": True}
        assert client.post("/sensitive", headers={"Origin": base}).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example:8765"},
        {"Host": "localhost.attacker.example"},
        {"Host": "user@127.0.0.1"},
        {"Host": "127.0.0.1:invalid"},
        {"Host": "127.0.0.1:0"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:9999"},
        {"Origin": "http://127.0.0.1:8765/"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_untrusted_browser_requests_cannot_reach_local_operations(
    headers: dict[str, str],
) -> None:
    with TestClient(_app(), base_url="http://127.0.0.1:8765") as client:
        for method in (client.get, client.post):
            response = method("/sensitive", headers=headers)
            assert response.status_code == 403
            assert "reached" not in response.json()


def test_testserver_is_not_trusted_in_production() -> None:
    with TestClient(_app()) as client:
        assert client.get("/sensitive").status_code == 403


def test_rejected_requests_keep_request_ids(client: TestClient) -> None:
    response = client.get("/healthz", headers={"Origin": "https://attacker.example"})
    assert response.status_code == 403
    assert response.headers["x-request-id"].startswith("req_")
