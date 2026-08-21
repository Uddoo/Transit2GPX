from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import osmium  # type: ignore[import-untyped]


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(path: Path) -> dict[str, Any]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise TypeError("Region manifest must contain a files list.")
    if not payload.get("dataset") or not payload.get("output_name"):
        raise ValueError("Region manifest must name its dataset and output.")
    return payload


def _download(entry: dict[str, Any], source_dir: Path) -> Path:
    name = str(entry["name"])
    expected_md5 = str(entry["md5"])
    output = source_dir / name
    if output.is_file():
        if _hash_file(output, "md5") != expected_md5:
            raise RuntimeError(f"Existing source has the wrong MD5: {output}")
        return output
    partial = source_dir / f".{name}.part"
    subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--retry",
            "5",
            "--retry-all-errors",
            "--continue-at",
            "-",
            "--silent",
            "--show-error",
            "--output",
            str(partial),
            str(entry["url"]),
        ],
        check=True,
    )
    actual_md5 = _hash_file(partial, "md5")
    if actual_md5 != expected_md5:
        raise RuntimeError(f"Downloaded source MD5 mismatch for {name}: {actual_md5}")
    os.replace(partial, output)
    return output


def _merge(sources: list[Path], output: Path) -> None:
    if len(sources) == 1:
        os.link(sources[0], output)
        return
    with tempfile.TemporaryDirectory(
        prefix=f".{output.stem}-", dir=output.parent
    ) as root:
        temporary = Path(root) / output.name
        reader = osmium.MergeInputReader()
        for source in sources:
            reader.add_file(str(source))
        writer = osmium.SimpleWriter(str(temporary), overwrite=False)
        try:
            reader.apply(writer)
        finally:
            writer.close()
        os.replace(temporary, output)


def prepare_region(manifest_path: Path, output_root: Path) -> Path:
    manifest = _manifest(manifest_path)
    dataset_dir = output_root / str(manifest["dataset"])
    source_dir = dataset_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    output = dataset_dir / str(manifest["output_name"])
    metadata_path = dataset_dir / "source-metadata.json"
    if output.exists():
        if not metadata_path.is_file():
            raise RuntimeError(f"Immutable output exists without metadata: {output}")
        return output
    sources = [_download(entry, source_dir) for entry in manifest["files"]]
    _merge(sources, output)
    metadata = {
        **{key: value for key, value in manifest.items() if key != "files"},
        "manifest": str(manifest_path.resolve()),
        "merged_sha256": _hash_file(output, "sha256"),
        "size_bytes": output.stat().st_size,
        "sources": [
            {
                **entry,
                "path": str(source.resolve()),
                "sha256": _hash_file(source, "sha256"),
                "size_bytes": source.stat().st_size,
            }
            for entry, source in zip(manifest["files"], sources, strict=True)
        ],
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download, verify and atomically merge a pinned Geofabrik region."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    output = prepare_region(args.manifest.resolve(), args.output_root.resolve())
    print(output)


if __name__ == "__main__":
    main()
