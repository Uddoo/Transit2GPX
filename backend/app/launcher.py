from __future__ import annotations

import argparse
import os
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from alembic import command
from alembic.config import Config

from app import __version__
from app.core.config import Settings, get_settings
from app.core.resources import resource_path


def upgrade_database(settings: Settings) -> None:
    config_path = resource_path("backend", "alembic.ini")
    migrations_path = resource_path("backend", "migrations")
    if not config_path.is_file() or not migrations_path.is_dir():
        raise RuntimeError("安装包缺少数据库迁移资源。")
    config = Config(config_path)
    config.set_main_option("script_location", str(migrations_path))
    config.attributes["database_url"] = settings.resolved_database_url
    command.upgrade(config, "head")


def _set_environment_default(name: str, value: str) -> None:
    # Do not shadow explicitly configured legacy values with a new-name default.
    if name.lower() not in Settings().model_fields_set:
        os.environ[f"TRANSIT2GPX_{name}"] = value


def _configure_environment(args: argparse.Namespace) -> Settings:
    _set_environment_default("ENVIRONMENT", "production")
    _set_environment_default("FRONTEND_DIST", str(resource_path("frontend", "dist")))
    if args.data_dir is not None:
        os.environ["TRANSIT2GPX_DATA_DIR"] = str(args.data_dir.resolve())
    if args.host is not None:
        os.environ["TRANSIT2GPX_HOST"] = args.host
    if args.port is not None:
        os.environ["TRANSIT2GPX_PORT"] = str(args.port)
    if args.rail:
        os.environ["TRANSIT2GPX_RAIL_ENABLED"] = "true"
        os.environ["TRANSIT2GPX_RAIL_SIDECAR_MANAGED"] = "true"
        _set_environment_default("RAIL_GRAPH_VERSION", "active")
    if args.rail_graph_root is not None:
        os.environ["TRANSIT2GPX_RAIL_GRAPH_ROOT"] = str(args.rail_graph_root.resolve())
    if args.rail_pbf is not None:
        os.environ["TRANSIT2GPX_RAIL_PBF_PATH"] = str(args.rail_pbf.resolve())
    if args.rail_sidecar_jar is not None:
        os.environ["TRANSIT2GPX_RAIL_SIDECAR_JAR"] = str(
            args.rail_sidecar_jar.resolve()
        )
    get_settings.cache_clear()
    return get_settings()


def _open_browser_when_ready(host: str, port: int) -> None:
    browser_host = "127.0.0.1" if host in {"localhost", "::1"} else host
    url = f"http://{browser_host}:{port}"
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=0.5):
                webbrowser.open(url)
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.25)


def package_smoke_test(settings: Settings) -> None:
    from pyproj import Transformer
    from shapely.geometry import LineString

    from app.main import create_app

    if not settings.resolved_rail_sidecar_config.is_file():
        raise RuntimeError("安装包缺少铁路 sidecar 配置。")
    schema_path = resource_path("app", "exports", "gpx.xsd")
    if not schema_path.is_file():
        schema_path = resource_path("backend", "app", "exports", "gpx.xsd")
    if not schema_path.is_file():
        raise RuntimeError("安装包缺少 GPX schema。")
    longitude, latitude = Transformer.from_crs(4326, 3857, always_xy=True).transform(
        121.47, 31.23
    )
    if longitude <= 0 or latitude <= 0 or LineString([(0, 0), (1, 1)]).length <= 0:
        raise RuntimeError("安装包的地理运行库不可用。")
    if not create_app().routes:
        raise RuntimeError("安装包没有 API 路由。")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Transit2GPX local application")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"))
    parser.add_argument("--port", type=int, choices=range(1, 65536), metavar="PORT")
    parser.add_argument("--rail", action="store_true")
    parser.add_argument("--rail-graph-root", type=Path)
    parser.add_argument("--rail-pbf", type=Path)
    parser.add_argument("--rail-sidecar-jar", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    args = _parser().parse_args()
    settings = _configure_environment(args)
    frontend_index = settings.resolved_frontend_dist / "index.html"
    if not frontend_index.is_file():
        raise SystemExit("安装包缺少前端生产资源。")
    upgrade_database(settings)
    if args.smoke_test:
        package_smoke_test(settings)
        print(f"Transit2GPX {__version__} package smoke test passed")
        return

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(settings.host, settings.port),
            name="transit2gpx-browser-launcher",
            daemon=True,
        ).start()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
