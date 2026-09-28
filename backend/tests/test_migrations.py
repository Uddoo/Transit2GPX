from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(
    database: Path, *arguments: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    runtime_dir = database.parent
    environment = {
        **os.environ,
        "TRANSIT2FOG_ENVIRONMENT": "test",
        "TRANSIT2FOG_DATA_DIR": str(runtime_dir),
        "TRANSIT2FOG_DATABASE_URL": f"sqlite:///{database}",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


def _columns(database: Path, table: str) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        return {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
        }


def _tables(database: Path) -> set[str]:
    with closing(sqlite3.connect(database)) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def test_model_metadata_matches_head_migration(tmp_path: Path) -> None:
    database = tmp_path / "metadata-check.sqlite3"
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")


def test_csv_job_migration_preserves_existing_review_progress(tmp_path: Path) -> None:
    database = tmp_path / "csv-jobs.sqlite3"
    _alembic(database, "upgrade", "20260821_0006")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "INSERT INTO import_batch (filename, encoding, total_rows, "
            "resolved_rows, review_rows, failed_rows, status) "
            "VALUES ('keep.csv', 'utf-8', 3, 2, 1, 0, 'ready_for_review')"
        )
    _alembic(database, "upgrade", "head")
    with closing(sqlite3.connect(database)) as connection, connection:
        assert connection.execute(
            "SELECT filename, processed_rows, resolved_rows, review_rows, "
            "run_token, error_message FROM import_batch"
        ).fetchone() == ("keep.csv", 3, 2, 1, None, None)
    _alembic(database, "check")
    _alembic(database, "downgrade", "20260821_0006")
    _alembic(database, "upgrade", "head")
    with closing(sqlite3.connect(database)) as connection, connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute(
            "SELECT processed_rows FROM import_batch"
        ).fetchone() == (3,)


@pytest.mark.parametrize("pending_index", [False, True])
def test_upgrade_from_retired_csv_revision_preserves_data(
    tmp_path: Path, pending_index: bool
) -> None:
    database = tmp_path / "legacy-csv.sqlite3"
    _alembic(database, "upgrade", "20260821_0006")
    # Reproduce the historical database independently of the restored migration.
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.executescript(
            "ALTER TABLE import_batch ADD COLUMN processed_rows INTEGER NOT NULL "
            "DEFAULT '0';"
            "ALTER TABLE import_batch ADD COLUMN run_token VARCHAR(32);"
            "ALTER TABLE import_batch ADD COLUMN error_message TEXT;"
            "UPDATE alembic_version SET version_num = '20260928_0007';"
        )
        if pending_index:
            connection.execute(
                "CREATE INDEX ix_import_row_pending "
                "ON import_row (batch_id, error_code, row_no)"
            )
        connection.execute(
            "INSERT INTO journey (journey_code, traveled_at, source_type, note) "
            "VALUES ('legacy-journey', '2026-09-28', 'manual', 'keep journey')"
        )
        connection.executemany(
            "INSERT INTO import_batch (filename, encoding, total_rows, "
            "resolved_rows, review_rows, failed_rows, status, processed_rows, "
            "run_token, error_message) VALUES (?, 'utf-8', 3, 1, 0, 0, ?, 1, ?, ?)",
            [
                ("parsing.csv", "parsing", "original-owner", None),
                ("review.csv", "ready_for_review", None, "preserve error"),
            ],
        )
        connection.execute(
            "INSERT INTO import_row (batch_id, row_no, raw_json, normalized_json, "
            "resolution_status, candidate_json) "
            "VALUES (1, 1, '{\"original\":true}', '{}', 'needs_review', '[]')"
        )
        original_batches = connection.execute(
            "SELECT * FROM import_batch ORDER BY id"
        ).fetchall()
        original_rows = connection.execute("SELECT * FROM import_row").fetchall()
        original_journeys = connection.execute("SELECT * FROM journey").fetchall()

    _alembic(database, "upgrade", "head")
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")

    assert {"app_task", "rail_station_fts"} <= _tables(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall() == [("20260928_0009",)]
        assert (
            connection.execute("SELECT * FROM import_batch ORDER BY id").fetchall()
            == original_batches
        )
        assert (
            connection.execute("SELECT * FROM import_row").fetchall() == original_rows
        )
        assert (
            connection.execute("SELECT * FROM journey").fetchall() == original_journeys
        )
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'rail_station%fts%'"
        ).fetchone() == (6,)
        assert connection.execute(
            "SELECT name FROM pragma_index_info('ix_import_row_pending') ORDER BY seqno"
        ).fetchall() == [("batch_id",), ("error_code",), ("row_no",)]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("revision", ["20260928_0007", "20260928_0008"])
def test_csv_merge_round_trip_retains_either_branch(
    tmp_path: Path, revision: str
) -> None:
    database = tmp_path / "csv-branches.sqlite3"
    _alembic(database, "upgrade", revision)
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "INSERT INTO import_batch (filename, encoding, total_rows, "
            "resolved_rows, review_rows, failed_rows, status, processed_rows) "
            "VALUES ('keep.csv', 'utf-8', 5, 2, 0, 0, 'ready_for_review', 2)"
        )
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")
    _alembic(database, "downgrade", revision)
    # Unmerging leaves both parents applied; remove only the other branch.
    other_revision = "20260928_0008" if revision == "20260928_0007" else "20260928_0007"
    _alembic(database, "downgrade", f"{other_revision}@20260821_0006")
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall() == [(revision,)]
        assert connection.execute(
            "SELECT filename, processed_rows, total_rows FROM import_batch"
        ).fetchone() == ("keep.csv", 2, 5)
    _alembic(database, "upgrade", "head")
    _alembic(database, "check")


def test_rail_migrations_round_trip_preserves_existing_journeys(tmp_path: Path) -> None:
    database = tmp_path / "migration.sqlite3"
    _alembic(database, "upgrade", "20260821_0003")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "INSERT INTO journey "
            "(journey_code, traveled_at, source_type, note) "
            "VALUES ('pre-rail-trip', '2026-08-20', 'manual', 'preserve me')"
        )

    _alembic(database, "upgrade", "head")

    assert "transport_mode" in _columns(database, "journey_leg")
    assert "matched_rail_start_station_id" in _columns(database, "import_row")
    assert "rail_journey_edge_snapshot" in _tables(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT journey_code FROM journey").fetchall() == [
            ("pre-rail-trip",)
        ]
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("20260928_0009",)

    _alembic(database, "downgrade", "20260821_0003")

    assert "transport_mode" not in _columns(database, "journey_leg")
    assert "matched_rail_start_station_id" not in _columns(database, "import_row")
    assert "rail_dataset_version" not in _tables(database)
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT journey_code FROM journey").fetchall() == [
            ("pre-rail-trip",)
        ]

    _alembic(database, "upgrade", "head")
    assert "rail_dataset_version" in _tables(database)


def test_task_migration_downgrade_refuses_active_jobs(tmp_path: Path) -> None:
    database = tmp_path / "task-guard.sqlite3"
    _alembic(database, "upgrade", "head")
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "INSERT INTO app_task "
            "(kind, resource_id, payload_json, status, attempts) "
            "VALUES ('cptond_import', 1, '{}', 'queued', 0)"
        )

    result = _alembic(database, "downgrade", "20260821_0006", check=False)

    assert result.returncode != 0
    assert "存在未完成的持久化任务" in result.stderr
    assert "app_task" in _tables(database)


def test_rail_migration_downgrade_refuses_user_rail_data(tmp_path: Path) -> None:
    database = tmp_path / "guard.sqlite3"
    _alembic(database, "upgrade", "head")
    with closing(sqlite3.connect(database)) as connection, connection:
        journey_id = connection.execute(
            "INSERT INTO journey "
            "(journey_code, traveled_at, source_type, note) "
            "VALUES ('rail-trip', '2026-08-20', 'manual', NULL) RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO journey_leg "
            "(journey_id, leg_no, transport_mode, dataset_version_id, city_id, "
            "line_id, route_variant_id, start_station_id, end_station_id, direction, "
            "resolution_status, resolution_message, candidate_digest) "
            "VALUES (?, 1, 'rail', NULL, NULL, NULL, NULL, NULL, NULL, "
            "'china_high_speed', 'resolved', NULL, ?)",
            (journey_id, f"sha256:{'a' * 64}"),
        )

    result = _alembic(database, "downgrade", "20260821_0003", check=False)

    assert result.returncode != 0
    assert "Cannot downgrade while rail journey legs exist" in result.stderr
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT transport_mode FROM journey_leg"
        ).fetchone() == ("rail",)


def test_csv_reference_migration_downgrade_refuses_review_data(
    tmp_path: Path,
) -> None:
    database = tmp_path / "csv-guard.sqlite3"
    _alembic(database, "upgrade", "head")
    with closing(sqlite3.connect(database)) as connection, connection:
        dataset_id = connection.execute(
            "INSERT INTO rail_dataset_version "
            "(source_name, source_url, source_timestamp, pbf_checksum, "
            "extract_region, graph_version, profile_version, "
            "openrailrouting_version, graphhopper_version, license, status, "
            "quality_flags_json) VALUES "
            "('OSM', 'local', '2026-08-20', ?, 'test', 'graph-v1', 'profile-v1', "
            "'orr-v1', 'gh-v1', 'ODbL-1.0', 'ready', '[]') RETURNING id",
            ("a" * 64,),
        ).fetchone()[0]
        station_id = connection.execute(
            "INSERT INTO rail_station "
            "(rail_dataset_version_id, osm_type, osm_id, name_cn, name_en, "
            "normalized_name, pinyin_full, pinyin_initials, station_code, "
            "city_name, province_name, lon, lat, match_status, quality_flags_json) "
            "VALUES (?, 'node', 1, '测试站', NULL, '测试站', NULL, NULL, NULL, "
            "NULL, NULL, 121, 31, 'ready', '[]') RETURNING id",
            (dataset_id,),
        ).fetchone()[0]
        batch_id = connection.execute(
            "INSERT INTO import_batch "
            "(filename, encoding, total_rows, resolved_rows, review_rows, "
            "failed_rows, status) VALUES "
            "('rail.csv', 'utf-8', 1, 0, 1, 0, 'ready_for_review') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO import_row "
            "(batch_id, row_no, raw_json, normalized_json, resolution_status, "
            "matched_rail_start_station_id, matched_rail_end_station_id, "
            "candidate_json) VALUES (?, 1, '{}', '{}', 'needs_review', ?, ?, '[]')",
            (batch_id, station_id, station_id),
        )

    result = _alembic(database, "downgrade", "20260821_0004", check=False)

    assert result.returncode != 0
    assert "CSV review rows reference rail stations" in result.stderr
    assert "matched_rail_start_station_id" in _columns(database, "import_row")
