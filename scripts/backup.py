from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "backend"))

from app import __version__
from app.core.config import get_settings


def database_path() -> Path:
    url = get_settings().resolved_database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit("备份脚本当前只支持 SQLite 数据库。")
    return Path(url.removeprefix("sqlite:///"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Transit2Fog local backup")
    parser.add_argument("output", type=Path, help="Output .zip path")
    args = parser.parse_args()
    source = database_path()
    if not source.is_file():
        raise SystemExit(f"数据库不存在：{source}")
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"备份目标已存在，拒绝覆盖：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="transit2fog-backup-") as temp_dir:
        snapshot = Path(temp_dir) / "transit2fog.sqlite3"
        with (
            closing(sqlite3.connect(source)) as source_db,
            closing(sqlite3.connect(snapshot)) as target_db,
        ):
            source_db.backup(target_db)
        checksum = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        manifest = {
            "format": "transit2fog-backup-v1",
            "app_version": __version__,
            "created_at": datetime.now(UTC).isoformat(),
            "database_sha256": checksum,
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "transit2fog.sqlite3")
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
    print(output)


if __name__ == "__main__":
    main()
