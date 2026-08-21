from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def _enable_sqlite_integrity(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
    del connection_record
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def build_engine(settings: Settings | None = None) -> Engine:
    runtime_settings = settings or get_settings()
    runtime_settings.ensure_runtime_directories()
    engine = create_engine(
        runtime_settings.resolved_database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    if runtime_settings.resolved_database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_integrity)
    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
