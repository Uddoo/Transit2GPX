from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_DIR / "backend"
RUNTIME_DIR = Path(tempfile.gettempdir()) / "transit2gpx-fullstack-e2e"
DATABASE_PATH = RUNTIME_DIR / "transit2gpx.sqlite3"


def _configure_environment() -> None:
    shutil.rmtree(RUNTIME_DIR, ignore_errors=True)
    RUNTIME_DIR.mkdir(parents=True)
    os.environ.update(
        {
            "TRANSIT2GPX_ENVIRONMENT": "production",
            "TRANSIT2GPX_HOST": "127.0.0.1",
            "TRANSIT2GPX_PORT": "8765",
            "TRANSIT2GPX_DATA_DIR": str(RUNTIME_DIR),
            "TRANSIT2GPX_DATABASE_URL": f"sqlite:///{DATABASE_PATH.as_posix()}",
            "TRANSIT2GPX_FRONTEND_DIST": str(PROJECT_DIR / "frontend" / "dist"),
            "TRANSIT2GPX_MAP_TILES_ENABLED": "false",
            "TRANSIT2GPX_RAIL_ENABLED": "false",
        }
    )


def _prepare_database() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=os.environ,
        check=True,
    )
    sys.path.insert(0, str(BACKEND_DIR / "tests"))
    from app.db.session import SessionLocal
    from factories import seed_linear_network

    with SessionLocal() as session:
        seed_linear_network(session)


def main() -> None:
    _configure_environment()
    frontend_dist = Path(os.environ["TRANSIT2GPX_FRONTEND_DIST"])
    if not (frontend_dist / "index.html").is_file():
        raise SystemExit("缺少 frontend/dist；请先运行前端生产构建。")
    _prepare_database()

    import uvicorn
    from app.main import create_app

    try:
        uvicorn.run(
            create_app(),
            host="127.0.0.1",
            port=8765,
            log_level="warning",
        )
    finally:
        from app.db.session import engine

        engine.dispose()
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
