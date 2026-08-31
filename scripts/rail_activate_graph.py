from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IDENTITY_FIELDS = (
    "graph_version",
    "pbf_sha256",
    "profile_version",
    "openrailrouting_commit",
)
_GRAPH_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ActivationError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ActivationError(f"Cannot read valid JSON from {path}.") from error
    if not isinstance(payload, dict):
        raise ActivationError(f"Expected a JSON object in {path}.")
    return payload


def _identity(payload: dict[str, Any], source: Path) -> dict[str, str]:
    identity: dict[str, str] = {}
    for field in IDENTITY_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ActivationError(f"{source} is missing {field}.")
        identity[field] = value
    return identity


def _selector_json_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.json")


def _valid_graph_version(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not _GRAPH_VERSION_RE.fullmatch(value)
        or value.startswith(".")
    ):
        return None
    return value


def _selector_version(path: Path) -> str | None:
    selector_json = _selector_json_path(path)
    legacy_exists = path.exists() or path.is_symlink()
    json_exists = selector_json.exists()
    if legacy_exists and json_exists:
        raise ActivationError(f"Selector is ambiguous: {path}")
    if legacy_exists:
        if not path.is_symlink():
            raise ActivationError(f"Refusing to replace non-symlink selector: {path}")
        target = Path(os.readlink(path))
        version = _valid_graph_version(target.name)
        if target.is_absolute() or len(target.parts) != 1 or version is None:
            raise ActivationError(f"Selector has an unsafe target: {path}")
        return version
    if json_exists:
        payload = _read_json(selector_json)
        version = _valid_graph_version(payload.get("graph_version"))
        if version is None:
            raise ActivationError(f"Selector has an unsafe target: {selector_json}")
        return version
    return None


def _replace_selector(path: Path, graph_version: str) -> None:
    if _valid_graph_version(graph_version) is None:
        raise ActivationError(f"Selector target is invalid: {graph_version}")
    selector_json = _selector_json_path(path)
    if path.exists() or path.is_symlink():
        if selector_json.exists():
            raise ActivationError(f"Selector is ambiguous: {path}")
        if not path.is_symlink():
            raise ActivationError(f"Refusing to replace non-symlink selector: {path}")
        temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
        temporary.unlink(missing_ok=True)
        os.symlink(graph_version, temporary)
        os.replace(temporary, path)
        return
    _write_json_atomic(selector_json, {"graph_version": graph_version})


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _metadata_path(graph_dir: Path) -> Path:
    current = graph_dir / "transit2fog-graph.json"
    return current if current.exists() else graph_dir / "metro2fog-graph.json"


def activate(
    graph_root: Path, graph_version: str, validation_report: Path
) -> dict[str, Any]:
    graph_root = graph_root.resolve()
    target = graph_root / graph_version
    metadata_path = _metadata_path(target)
    if graph_version in {"active", "previous"} or not target.is_dir():
        raise ActivationError(f"Graph version does not exist: {graph_version}")
    graph_identity = _identity(_read_json(metadata_path), metadata_path)
    if graph_identity["graph_version"] != graph_version:
        raise ActivationError("Graph directory and metadata version do not match.")
    report = _read_json(validation_report)
    if report.get("status") != "passed" or report.get("graph_version") != graph_version:
        raise ActivationError("Validation report does not approve the selected graph.")
    sidecar_identity = report.get("sidecar_identity")
    if (
        not isinstance(sidecar_identity, dict)
        or _identity(sidecar_identity, validation_report) != graph_identity
    ):
        raise ActivationError(
            "Validation report sidecar identity does not match graph metadata."
        )
    current = _selector_version(graph_root / "active")
    if current and current != graph_version:
        _replace_selector(graph_root / "previous", current)
    _replace_selector(graph_root / "active", graph_version)
    result = {
        "status": "activated",
        "active_graph_version": graph_version,
        "previous_graph_version": current
        if current != graph_version
        else _selector_version(graph_root / "previous"),
        "activated_at": datetime.now(UTC).isoformat(),
        "validation_report": str(validation_report.resolve()),
        "validation_report_sha256": hashlib.sha256(
            validation_report.read_bytes()
        ).hexdigest(),
        "identity": graph_identity,
    }
    _write_json_atomic(graph_root / "activation.json", result)
    return result


def rollback(graph_root: Path) -> dict[str, Any]:
    graph_root = graph_root.resolve()
    current = _selector_version(graph_root / "active")
    previous = _selector_version(graph_root / "previous")
    if current is None or previous is None or not (graph_root / previous).is_dir():
        raise ActivationError(
            "No valid previous graph version is available for rollback."
        )
    _replace_selector(graph_root / "active", previous)
    _replace_selector(graph_root / "previous", current)
    result = {
        "status": "rolled_back",
        "active_graph_version": previous,
        "previous_graph_version": current,
        "activated_at": datetime.now(UTC).isoformat(),
    }
    _write_json_atomic(graph_root / "activation.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Atomically activate or roll back an immutable railway graph."
    )
    parser.add_argument("--graph-root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    activate_parser = subparsers.add_parser("activate")
    activate_parser.add_argument("graph_version")
    activate_parser.add_argument("--validation-report", type=Path, required=True)
    subparsers.add_parser("rollback")
    args = parser.parse_args()
    try:
        result = (
            activate(args.graph_root, args.graph_version, args.validation_report)
            if args.command == "activate"
            else rollback(args.graph_root)
        )
    except ActivationError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
