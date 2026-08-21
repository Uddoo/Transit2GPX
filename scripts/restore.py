from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "backend"))

from app.core.config import get_settings


def database_path() -> Path:
    url = get_settings().resolved_database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit("恢复脚本当前只支持 SQLite 数据库。")
    return Path(url.removeprefix("sqlite:///"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a Metro2Fog local backup")
    parser.add_argument("backup", type=Path, help="Backup .zip path")
    parser.add_argument("--yes", action="store_true", help="Confirm replacement")
    args = parser.parse_args()
    if not args.yes:
        raise SystemExit("恢复会替换当前数据库；确认后请添加 --yes。")
    backup = args.backup.expanduser().resolve()
    if not backup.is_file():
        raise SystemExit(f"备份不存在：{backup}")
    target = database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="metro2fog-restore-") as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(backup) as archive:
            if set(archive.namelist()) != {"metro2fog.sqlite3", "manifest.json"}:
                raise SystemExit("备份内容不符合 Metro2Fog 格式。")
            archive.extractall(temp_path)
        snapshot = temp_path / "metro2fog.sqlite3"
        manifest = json.loads((temp_path / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != "metro2fog-backup-v1":
            raise SystemExit("不支持的备份格式。")
        checksum = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        if checksum != manifest.get("database_sha256"):
            raise SystemExit("备份校验和不匹配。")
        with sqlite3.connect(snapshot) as restored:
            if restored.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise SystemExit("备份数据库完整性检查失败。")
        if target.exists():
            timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            safety_copy = target.with_name(f"{target.name}.pre-restore-{timestamp}.bak")
            shutil.copy2(target, safety_copy)
            print(f"原数据库安全副本：{safety_copy}")
        replacement = target.with_suffix(target.suffix + ".restore")
        shutil.copy2(snapshot, replacement)
        os.replace(replacement, target)
    print(f"已恢复：{target}")


if __name__ == "__main__":
    main()
