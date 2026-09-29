"""Build one pinned, licensed optional runtime and its embedded download manifest."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import quote

from app.rail.components import RuntimeManifest, platform_tag, sha256_file, verify_java

PROJECT_DIR = Path(__file__).resolve().parents[1]


def sidecar_notices(jar: Path) -> list[Path]:
    upstream = jar.parent.parent / "upstream"
    paths = [
        upstream / "OpenRailRouting" / "LICENSE.txt",
        upstream / "OpenRailRouting" / "THIRD_PARTY.md",
        upstream / "GraphHopper" / "LICENSE.txt",
        upstream / "GraphHopper" / "NOTICE.md",
    ]
    if not jar.is_file() or jar.name != "openrailrouting.jar":
        raise SystemExit("必须提供已经固定构建的 openrailrouting.jar。")
    if any(not path.is_file() for path in paths):
        raise SystemExit("缺少铁路组件第三方许可文件。")
    return paths


def build_components(jar: Path, output: Path, release_tag: str) -> tuple[Path, Path]:
    notices = sidecar_notices(jar)
    tag = platform_tag()
    pins = json.loads((PROJECT_DIR / "packaging" / "java-runtimes.json").read_text())
    if tag not in pins:
        raise SystemExit(f"尚未锁定 {tag} 的 Java 运行时。")
    pin = pins[tag]
    output.mkdir(parents=True, exist_ok=True)
    cache = PROJECT_DIR / "release" / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    java_archive = cache / Path(pin["url"]).name
    if not java_archive.is_file() or sha256_file(java_archive) != pin["sha256"]:
        partial = java_archive.with_suffix(".part")
        with (
            urllib.request.urlopen(pin["url"], timeout=60) as response,
            partial.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)
        if sha256_file(partial) != pin["sha256"]:
            raise SystemExit("Java 运行时 SHA-256 校验失败。")
        partial.replace(java_archive)
    filename = f"Transit2Fog-rail-components-{tag}.zip"
    archive = output / filename
    with tempfile.TemporaryDirectory(prefix="rail-components-") as temporary:
        root = Path(temporary)
        extracted = root / "extracted"
        if java_archive.suffix == ".zip":
            with zipfile.ZipFile(java_archive) as source:
                source.extractall(extracted)  # Pinned official build-time archive.
        else:
            with tarfile.open(java_archive) as source:
                source.extractall(extracted, filter="data")
        java_name = "java.exe" if tag.startswith("windows") else "java"
        java_binaries = list(extracted.rglob(f"bin/{java_name}"))
        if len(java_binaries) != 1:
            raise SystemExit("Java 归档中未找到唯一运行时。")
        bundle = root / "bundle"
        bundle.mkdir()
        shutil.copytree(java_binaries[0].parent.parent, bundle / "java")
        shutil.copy2(jar, bundle / "openrailrouting.jar")
        for notice in notices:
            destination = bundle / "licenses" / notice.parent.name.lower()
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(notice, destination / notice.name)
        shutil.copy2(
            PROJECT_DIR / "rail-routing" / "versions.env", bundle / "versions.env"
        )
        (bundle / "JAVA-SOURCE.txt").write_text(
            f"Eclipse Temurin JRE {pins['version']}\n{pin['url']}\nSHA-256: {pin['sha256']}\n"
            "Source: https://github.com/adoptium/temurin21-binaries\n"
            "The complete upstream license and legal directory are retained under java/.\n",
            encoding="utf-8",
        )
        verify_java(bundle)
        files = sorted(path for path in bundle.rglob("*") if path.is_file())
        size = sum(path.stat().st_size for path in files)
        with zipfile.ZipFile(
            archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as target:
            for path in files:
                info = zipfile.ZipInfo.from_file(
                    path, path.relative_to(bundle).as_posix()
                )
                info.date_time = (2026, 8, 31, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as source, target.open(info, "w") as destination:
                    shutil.copyfileobj(source, destination)
    versions = dict(
        line.split("=", 1)
        for line in (PROJECT_DIR / "rail-routing" / "versions.env")
        .read_text()
        .splitlines()
        if line and not line.startswith("#")
    )
    manifest = RuntimeManifest(
        platform=tag,
        url=f"https://github.com/Uddoo/transit2fog/releases/download/{quote(release_tag, safe='')}/{filename}",
        sha256=sha256_file(archive),
        size=archive.stat().st_size,
        unpacked_size=size,
        java_version=pins["version"],
        sidecar_commit=versions["OPENRAILROUTING_COMMIT"],
    )
    manifest_path = (
        PROJECT_DIR / "release" / "component-manifests" / tag / "components.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return archive, manifest_path
