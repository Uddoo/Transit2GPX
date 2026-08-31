from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rail_activate_graph.py"


def _identity(graph_version: str, suffix: str) -> dict[str, str]:
    return {
        "graph_version": graph_version,
        "pbf_sha256": suffix * 64,
        "profile_version": "2026-08-21-r0.1",
        "openrailrouting_commit": "c8d4ef1",
    }


def _prepare_version(root: Path, graph_version: str, suffix: str) -> Path:
    graph_dir = root / graph_version
    graph_dir.mkdir()
    identity = _identity(graph_version, suffix)
    (graph_dir / "transit2fog-graph.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )
    report = root / f"{graph_version}-validation.json"
    report.write_text(
        json.dumps(
            {
                "status": "passed",
                "graph_version": graph_version,
                "sidecar_identity": identity,
            }
        ),
        encoding="utf-8",
    )
    return report


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--graph-root", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _selector(root: Path, name: str) -> str:
    payload = json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
    return str(payload["graph_version"])


def test_graph_activation_is_atomic_and_can_roll_back(tmp_path: Path) -> None:
    first_report = _prepare_version(tmp_path, "china-v1", "a")
    second_report = _prepare_version(tmp_path, "china-v2", "b")

    first = _run(
        tmp_path,
        "activate",
        "china-v1",
        "--validation-report",
        str(first_report),
    )
    second = _run(
        tmp_path,
        "activate",
        "china-v2",
        "--validation-report",
        str(second_report),
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert _selector(tmp_path, "active") == "china-v2"
    assert _selector(tmp_path, "previous") == "china-v1"

    rolled_back = _run(tmp_path, "rollback")

    assert rolled_back.returncode == 0, rolled_back.stderr
    assert _selector(tmp_path, "active") == "china-v1"
    assert _selector(tmp_path, "previous") == "china-v2"


def test_graph_activation_rejects_mismatched_sidecar_identity(tmp_path: Path) -> None:
    report = _prepare_version(tmp_path, "china-v1", "a")
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["sidecar_identity"]["pbf_sha256"] = "b" * 64
    report.write_text(json.dumps(payload), encoding="utf-8")

    result = _run(
        tmp_path,
        "activate",
        "china-v1",
        "--validation-report",
        str(report),
    )

    assert result.returncode != 0
    assert "identity does not match" in result.stderr
    assert not (tmp_path / "active.json").exists()


def test_graph_activation_accepts_legacy_metadata_filename(tmp_path: Path) -> None:
    report = _prepare_version(tmp_path, "china-v1", "a")
    graph_dir = tmp_path / "china-v1"
    (graph_dir / "transit2fog-graph.json").rename(graph_dir / "metro2fog-graph.json")

    result = _run(
        tmp_path,
        "activate",
        "china-v1",
        "--validation-report",
        str(report),
    )

    assert result.returncode == 0, result.stderr
    assert _selector(tmp_path, "active") == "china-v1"
