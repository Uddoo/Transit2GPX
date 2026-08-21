from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from app import __version__
from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import install_request_id_middleware
from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.db.search import ensure_search_indexes
from app.db.session import engine


class SPAStaticFiles(StaticFiles):
    """Serve index.html for client-side routes while preserving real assets."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
            return await super().get_response("index.html", scope)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    del app
    settings = get_settings()
    settings.ensure_runtime_directories()
    # Alembic owns production migrations. create_all keeps an empty first-run
    # development checkout operational until the initial migration is applied.
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_search_indexes(connection)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(
        title="Transit2Fog API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        redoc_url=None,
    )
    install_request_id_middleware(app)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router)

    frontend_dist = settings.resolved_frontend_dist
    if frontend_dist.is_dir():
        app.mount(
            "/",
            SPAStaticFiles(directory=frontend_dist, html=True),
            name="frontend",
        )
    return app


app = create_app()
