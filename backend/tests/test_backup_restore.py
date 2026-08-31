from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]


def _environment(database: Path) -> dict[str, str]:
    return {
        **os.environ,
        "TRANSIT2FOG_ENVIRONMENT": "test",
        "TRANSIT2FOG_DATA_DIR": str(database.parent),
        "TRANSIT2FOG_DATABASE_URL": f"sqlite:///{database}",
    }


def _run_script(
    script: str,
    database: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROJECT_DIR / "scripts" / script), *arguments],
        cwd=PROJECT_DIR,
        env=_environment(database),
        check=check,
        capture_output=True,
        text=True,
    )


def test_backup_restore_preserves_railway_snapshot_data(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute(
            "CREATE TABLE rail_snapshot "
            "(id INTEGER PRIMARY KEY, graph_version TEXT, geometry_sha256 TEXT)"
        )
        connection.execute(
            "INSERT INTO rail_snapshot VALUES (1, 'china-20260815-r3.1', ?)",
            ("a" * 64,),
        )
    backup = tmp_path / "backup.zip"

    _run_script("backup.py", source, str(backup))

    restored = tmp_path / "restored.sqlite3"
    with closing(sqlite3.connect(restored)) as connection, connection:
        connection.execute("CREATE TABLE old_data (value TEXT)")
        connection.execute("INSERT INTO old_data VALUES ('safety copy')")
    _run_script("restore.py", restored, str(backup), "--yes")

    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute(
            "SELECT graph_version, geometry_sha256 FROM rail_snapshot"
        ).fetchone() == ("china-20260815-r3.1", "a" * 64)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    safety_copies = list(tmp_path.glob("restored.sqlite3.pre-restore-*.bak"))
    assert len(safety_copies) == 1
    with closing(sqlite3.connect(safety_copies[0])) as connection:
        assert connection.execute("SELECT value FROM old_data").fetchone() == (
            "safety copy",
        )


def test_restore_rejects_checksum_tampering(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE proof (value TEXT)")
        connection.execute("INSERT INTO proof VALUES ('original')")
    backup = tmp_path / "backup.zip"
    _run_script("backup.py", source, str(backup))

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(backup) as source_archive:
        manifest = json.loads(source_archive.read("manifest.json"))
    with zipfile.ZipFile(tampered, "w") as archive:
        archive.writestr("transit2fog.sqlite3", b"not the original database")
        archive.writestr("manifest.json", json.dumps(manifest))

    target = tmp_path / "target.sqlite3"
    result = _run_script("restore.py", target, str(tampered), "--yes", check=False)

    assert result.returncode != 0
    assert "备份校验和不匹配" in result.stderr
    assert not target.exists()


def test_backup_refuses_to_overwrite_existing_archive(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE proof (value TEXT)")
    backup = tmp_path / "backup.zip"
    backup.write_bytes(b"keep-me")

    result = _run_script("backup.py", source, str(backup), check=False)

    assert result.returncode != 0
    assert "拒绝覆盖" in result.stderr
    assert backup.read_bytes() == b"keep-me"


def test_restore_accepts_legacy_metro2fog_backup(tmp_path: Path) -> None:
    source = tmp_path / "legacy.sqlite3"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE legacy_proof (value TEXT)")
        connection.execute("INSERT INTO legacy_proof VALUES ('kept')")
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()
    backup = tmp_path / "legacy-backup.zip"
    with zipfile.ZipFile(backup, "w") as archive:
        archive.writestr("metro2fog.sqlite3", source.read_bytes())
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "metro2fog-backup-v1",
                    "database_sha256": checksum,
                }
            ),
        )

    restored = tmp_path / "restored.sqlite3"
    _run_script("restore.py", restored, str(backup), "--yes")

    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute("SELECT value FROM legacy_proof").fetchone() == (
            "kept",
        )
