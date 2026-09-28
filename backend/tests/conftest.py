from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings


@pytest.fixture(scope="session")
def client(tmp_path_factory: pytest.TempPathFactory) -> Generator[TestClient]:
    runtime_dir = tmp_path_factory.mktemp("runtime")
    os.environ["TRANSIT2FOG_ENVIRONMENT"] = "test"
    os.environ["TRANSIT2FOG_DATA_DIR"] = str(runtime_dir)
    os.environ["TRANSIT2FOG_DATABASE_URL"] = f"sqlite:///{runtime_dir / 'test.sqlite3'}"
    get_settings.cache_clear()

    backend_dir = Path(__file__).resolve().parents[1]
    alembic = Config(backend_dir / "alembic.ini")
    alembic.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(alembic, "head")

    # Imported after the test settings and migrated database are installed
    # because the first engine is intentionally constructed once per process.
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    from app.db.session import engine

    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def db(client: TestClient) -> Generator[Session]:
    del client
    from app.db.models import (
        AppTask,
        DatasetVersion,
        ImportBatch,
        Journey,
        RailDatasetVersion,
    )
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        session.execute(delete(AppTask))
        session.execute(delete(ImportBatch))
        session.execute(delete(Journey))
        session.execute(delete(RailDatasetVersion))
        session.execute(delete(DatasetVersion))
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(AppTask))
        session.execute(delete(ImportBatch))
        session.execute(delete(Journey))
        session.execute(delete(RailDatasetVersion))
        session.execute(delete(DatasetVersion))
        session.commit()
