"""Browser boundary for the single-user, loopback-only local application."""

from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            return None
        port = parsed.port
        if port == 0:
            return None
        return (
            parsed.scheme,
            parsed.hostname,
            port or (443 if parsed.scheme == "https" else 80),
        )
    except ValueError:
        return None


class LocalRequestMiddleware:
    def __init__(self, app: ASGIApp, *, testing: bool = False) -> None:
        self.app = app
        self.hosts = {"127.0.0.1", "localhost", "::1"}
        if testing:
            self.hosts.add("testserver")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        authority = headers.getlist("host")
        origins = headers.getlist("origin")
        current = (
            _origin(f"{scope['scheme']}://{authority[0]}")
            if len(authority) == 1
            else None
        )
        if (
            current is None
            or current[1] not in self.hosts
            or headers.get("sec-fetch-site") == "cross-site"
            or (origins and (len(origins) != 1 or _origin(origins[0]) != current))
        ):
            response = JSONResponse(
                {"detail": "Only local, same-origin requests are accepted."},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        # Header-less CLI calls remain supported. A hostile website cannot set
        # its own Host/Origin headers, including after DNS rebinding to loopback.
        await self.app(scope, receive, send)
