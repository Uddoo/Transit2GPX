from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
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
from app.db.search import ensure_search_indexes
from app.db.session import SessionLocal, engine
from app.importers.recovery import recover_interrupted_imports
from app.rail.components import ComponentInstaller
from app.rail.service import RailServiceController
from app.services.onboarding import restore_rail_preferences
from app.tasks import task_executor


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
    settings = get_settings()
    settings.ensure_runtime_directories()
    # Alembic owns all schema changes. Refuse to let create_all partially apply
    # a new model revision to an older user database.
    with engine.begin() as connection:
        inspector = inspect(connection)
        if not inspector.has_table("app_task") or not {
            "processed_rows",
            "run_token",
            "error_message",
        }.issubset(
            {column["name"] for column in inspector.get_columns("import_batch")}
        ):
            raise RuntimeError(
                "数据库结构不是最新版本；请先运行 scripts/project.py db-upgrade。"
            )
        ensure_search_indexes(connection)
    with SessionLocal() as db:
        recover_interrupted_imports(db)
    controller = RailServiceController(settings)
    app.state.rail_service = controller
    app.state.rail_components = ComponentInstaller(settings)
    with SessionLocal() as db:
        restore_rail_preferences(db, settings)
    if settings.rail_enabled and settings.rail_sidecar_managed:
        controller.start()
    task_executor.start()
    try:
        yield
    finally:
        app.state.rail_components.stop()
        task_executor.stop()
        controller.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    app = FastAPI(
        title="Transit2Fog API",
        version=__version__,
        license_info={
            "name": "Apache License 2.0",
            "identifier": "Apache-2.0",
        },
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
