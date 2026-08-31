from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import NoReturn

PROJECT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_DIR / "backend"
FRONTEND_DIR = PROJECT_DIR / "frontend"


def _required_command(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise SystemExit(f"缺少必需命令：{name}")
    return command


def _run(
    *args: str, cwd: Path = PROJECT_DIR, env: dict[str, str] | None = None
) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def _uv(*args: str, cwd: Path = PROJECT_DIR, env: dict[str, str] | None = None) -> None:
    _run(_required_command("uv"), *args, cwd=cwd, env=env)


def _npm(*args: str, cwd: Path = PROJECT_DIR) -> None:
    _run(_required_command("npm"), *args, cwd=cwd)


def setup() -> None:
    _uv("sync", "--project", str(BACKEND_DIR), "--dev")
    _npm("ci", "--prefix", str(FRONTEND_DIR))


def build() -> None:
    _npm("run", "build", "--prefix", str(FRONTEND_DIR))


def backend_check() -> None:
    source_paths = (
        str(BACKEND_DIR / "app"),
        str(BACKEND_DIR / "tests"),
        str(BACKEND_DIR / "migrations"),
        str(PROJECT_DIR / "scripts"),
    )
    _uv("run", "--project", str(BACKEND_DIR), "ruff", "check", *source_paths)
    _uv(
        "run",
        "--project",
        str(BACKEND_DIR),
        "ruff",
        "format",
        "--check",
        *source_paths,
    )
    _uv(
        "run",
        "--project",
        str(BACKEND_DIR),
        "mypy",
        str(BACKEND_DIR / "app"),
    )
    _uv(
        "run",
        "--project",
        str(BACKEND_DIR),
        "pytest",
        str(BACKEND_DIR / "tests"),
        "--cov=backend/app",
        "--cov-report=term-missing",
        "--cov-fail-under=85",
    )


def frontend_check() -> None:
    for task in ("api:check", "lint", "test:coverage", "build"):
        _npm("run", task, "--prefix", str(FRONTEND_DIR))


def check() -> None:
    backend_check()
    frontend_check()


def tests() -> None:
    _uv(
        "run",
        "--project",
        str(BACKEND_DIR),
        "pytest",
        str(BACKEND_DIR / "tests"),
    )
    _npm("run", "test", "--prefix", str(FRONTEND_DIR))


def e2e() -> None:
    build()
    _npm("run", "test:e2e", "--prefix", str(FRONTEND_DIR))
    _npm("run", "test:e2e:fullstack", "--prefix", str(FRONTEND_DIR))


def db_upgrade() -> None:
    _uv("run", "alembic", "upgrade", "head", cwd=BACKEND_DIR)


def _backend_environment(environment: str, *, rail: bool) -> dict[str, str]:
    child_environment = os.environ.copy()
    child_environment["TRANSIT2FOG_ENVIRONMENT"] = environment
    if rail:
        rail_work_dir = Path(
            child_environment.get(
                "RAIL_WORK_DIR", str(PROJECT_DIR / "data" / "rail-routing")
            )
        )
        child_environment.update(
            {
                "TRANSIT2FOG_RAIL_ENABLED": "true",
                "TRANSIT2FOG_RAIL_SIDECAR_MANAGED": "true",
                "TRANSIT2FOG_RAIL_GRAPH_VERSION": "active",
                "TRANSIT2FOG_RAIL_GRAPH_ROOT": child_environment.get(
                    "RAIL_GRAPH_ROOT", str(rail_work_dir / "graphs")
                ),
                "TRANSIT2FOG_RAIL_SIDECAR_JAR": child_environment.get(
                    "TRANSIT2FOG_RAIL_SIDECAR_JAR",
                    str(rail_work_dir / "dist" / "openrailrouting.jar"),
                ),
                "TRANSIT2FOG_RAIL_SIDECAR_URL": "http://127.0.0.1:8989",
            }
        )
    return child_environment


def _spawn_backend(*, rail: bool) -> subprocess.Popen[bytes]:
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    return subprocess.Popen(
        [_required_command("uv"), "run", "python", "-m", "app"],
        cwd=BACKEND_DIR,
        env=_backend_environment("development", rail=rail),
        **options,  # type: ignore[arg-type]
    )


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def dev(*, rail: bool) -> None:
    db_upgrade()
    backend = _spawn_backend(rail=rail)
    try:
        time.sleep(0.75)
        exit_code = backend.poll()
        if exit_code is not None:
            raise SystemExit(f"后端启动失败（退出码 {exit_code}）。")
        _npm("run", "dev", cwd=FRONTEND_DIR)
    finally:
        _stop_process_tree(backend)


def start(*, rail: bool) -> None:
    build()
    db_upgrade()
    _uv(
        "run",
        "python",
        "-m",
        "app",
        cwd=BACKEND_DIR,
        env=_backend_environment("production", rail=rail),
    )


def backup(output: Path) -> None:
    _uv(
        "run",
        "--project",
        str(BACKEND_DIR),
        "python",
        str(PROJECT_DIR / "scripts" / "backup.py"),
        str(output),
    )


def package(output: Path, sidecar_jar: Path | None) -> None:
    arguments = [
        "run",
        "--project",
        str(BACKEND_DIR),
        "python",
        str(PROJECT_DIR / "scripts" / "build_package.py"),
        "--output",
        str(output),
    ]
    if sidecar_jar is not None:
        arguments.extend(("--sidecar-jar", str(sidecar_jar)))
    _uv(*arguments)


def validate_real_data(directory: Path) -> None:
    _uv(
        "run",
        "--project",
        str(BACKEND_DIR),
        "python",
        str(PROJECT_DIR / "scripts" / "validate_cptond.py"),
        str(directory),
    )


def _parser_error(parser: argparse.ArgumentParser, message: str) -> NoReturn:
    parser.error(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transit2Fog cross-platform tasks")
    parser.add_argument(
        "command",
        choices=(
            "setup",
            "build",
            "backend-check",
            "frontend-check",
            "check",
            "test",
            "e2e",
            "db-upgrade",
            "dev",
            "start",
            "package",
            "backup",
            "validate-real-data",
        ),
    )
    parser.add_argument("--rail", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sidecar-jar", type=Path)
    parser.add_argument("--cptond-dir", type=Path)
    args = parser.parse_args()

    commands = {
        "setup": setup,
        "build": build,
        "backend-check": backend_check,
        "frontend-check": frontend_check,
        "check": check,
        "test": tests,
        "e2e": e2e,
        "db-upgrade": db_upgrade,
    }
    if args.command == "dev":
        dev(rail=args.rail)
    elif args.command == "start":
        start(rail=args.rail)
    elif args.command == "package":
        package(
            (args.output or PROJECT_DIR / "release" / "packages").resolve(),
            args.sidecar_jar.resolve() if args.sidecar_jar else None,
        )
    elif args.command == "backup":
        backup((args.output or Path("transit2fog-backup.zip")).resolve())
    elif args.command == "validate-real-data":
        if args.cptond_dir is None:
            _parser_error(parser, "validate-real-data 需要 --cptond-dir")
        validate_real_data(args.cptond_dir.resolve())
    else:
        commands[args.command]()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
