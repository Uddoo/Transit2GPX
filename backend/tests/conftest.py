from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings


@pytest.fixture(scope="session")
def client(tmp_path_factory: pytest.TempPathFactory) -> Generator[TestClient]:
    runtime_dir = tmp_path_factory.mktemp("runtime")
    os.environ["METRO2FOG_ENVIRONMENT"] = "test"
    os.environ["METRO2FOG_DATA_DIR"] = str(runtime_dir)
    os.environ["METRO2FOG_DATABASE_URL"] = f"sqlite:///{runtime_dir / 'test.sqlite3'}"
    get_settings.cache_clear()

    # Imported after the test settings are installed because the first engine
    # is intentionally constructed once per process.
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


@pytest.fixture
def db(client: TestClient) -> Generator[Session]:
    del client
    from app.db.models import DatasetVersion, ImportBatch, Journey
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        session.execute(delete(ImportBatch))
        session.execute(delete(Journey))
        session.execute(delete(DatasetVersion))
        session.commit()
        yield session
        session.rollback()
        session.execute(delete(ImportBatch))
        session.execute(delete(Journey))
        session.execute(delete(DatasetVersion))
        session.commit()
