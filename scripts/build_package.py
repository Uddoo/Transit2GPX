from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from build_rail_components import build_components, sidecar_notices

PROJECT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_DIR / "frontend"
RELEASE_DIR = PROJECT_DIR / "release"


def _run(
    *args: str, cwd: Path = PROJECT_DIR, env: dict[str, str] | None = None
) -> None:
    subprocess.run(args, cwd=cwd, env=env, check=True)


def _version() -> str:
    payload = json.loads((FRONTEND_DIR / "package.json").read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise SystemExit("frontend/package.json 缺少版本。")
    return version


def _platform_tag() -> str:
    system = {"Windows": "windows", "Darwin": "macos"}.get(
        platform.system(), platform.system().lower()
    )
    machine = platform.machine().lower()
    architecture = "x64" if machine in {"amd64", "x86_64"} else machine
    return f"{system}-{architecture}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_checksum(path: Path) -> None:
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{_sha256(path)}  {path.name}\n", encoding="utf-8", newline="\n"
    )


def _copy_release_documents(destination: Path) -> None:
    for filename in ("LICENSE", "NOTICE", "ATTRIBUTION.md"):
        shutil.copy2(PROJECT_DIR / filename, destination / filename)


def _smoke_test(executable: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="transit2fog-package-smoke-") as directory:
        environment = os.environ.copy()
        environment.update(
            {
                "TRANSIT2FOG_ENVIRONMENT": "production",
                "TRANSIT2FOG_MAP_TILES_ENABLED": "false",
                "TRANSIT2FOG_RAIL_ENABLED": "false",
            }
        )
        _run(
            str(executable),
            "--smoke-test",
            "--no-browser",
            "--data-dir",
            directory,
            env=environment,
        )


def _verify_base_libraries(root: Path, with_import_tools: bool) -> None:
    if with_import_tools:
        return
    forbidden = {"pandas", "pandas.libs", "geopandas", "pyogrio", "pyogrio.libs"}
    if any(path.name.lower() in forbidden for path in root.rglob("*")):
        raise SystemExit("轻量构建意外包含重型 GIS 导入依赖。")


def build_package(args: argparse.Namespace) -> list[Path]:
    version = _version()
    if not args.skip_frontend:
        npm = shutil.which("npm")
        if npm is None:
            raise SystemExit("缺少必需命令：npm")
        _run(npm, "run", "build", "--prefix", str(FRONTEND_DIR))
    if not (FRONTEND_DIR / "dist" / "index.html").is_file():
        raise SystemExit("缺少 frontend/dist；请先构建前端。")

    stage_dir = RELEASE_DIR / "stage"
    work_dir = RELEASE_DIR / "pyinstaller"
    output_dir = args.output.resolve()
    shutil.rmtree(stage_dir, ignore_errors=True)
    shutil.rmtree(work_dir, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    # A previous shell/build must not silently turn a light build into a full one.
    for key in (
        "TRANSIT2FOG_PACKAGE_SIDECAR_JAR",
        "TRANSIT2FOG_PACKAGE_SIDECAR_NOTICES",
        "TRANSIT2FOG_PACKAGE_COMPONENT_MANIFEST",
    ):
        environment.pop(key, None)
    environment.setdefault("SOURCE_DATE_EPOCH", "1788134400")
    environment["TRANSIT2FOG_PACKAGE_IMPORT_TOOLS"] = (
        "1" if args.with_import_tools else "0"
    )
    artifacts: list[Path] = []
    if args.rail_components:
        if not args.sidecar_jar or not args.release_tag:
            raise SystemExit("按需组件构建需要 --sidecar-jar 和 --release-tag。")
        component_archive, manifest = build_components(
            args.sidecar_jar.resolve(), output_dir, args.release_tag
        )
        environment["TRANSIT2FOG_PACKAGE_COMPONENT_MANIFEST"] = str(manifest)
        artifacts.append(component_archive)
    if args.sidecar_jar:
        sidecar_jar = args.sidecar_jar.resolve()
        notice_paths = sidecar_notices(sidecar_jar)
        if not args.rail_components:
            environment["TRANSIT2FOG_PACKAGE_SIDECAR_JAR"] = str(sidecar_jar)
            environment["TRANSIT2FOG_PACKAGE_SIDECAR_NOTICES"] = json.dumps(
                [str(path) for path in notice_paths]
            )
    _run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(stage_dir),
        "--workpath",
        str(work_dir),
        str(PROJECT_DIR / "packaging" / "transit2fog.spec"),
        env=environment,
    )

    artifact_base = f"Transit2Fog-{version}-{_platform_tag()}"
    if platform.system() == "Darwin":
        application = stage_dir / "Transit2Fog.app"
        executable = application / "Contents" / "MacOS" / "Transit2Fog"
        if not executable.is_file():
            raise SystemExit("PyInstaller 没有生成 Transit2Fog.app。")
        _verify_base_libraries(application, args.with_import_tools)
        if not args.no_smoke:
            _smoke_test(executable)
        archive = output_dir / f"{artifact_base}.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            stream.add(application, arcname=application.name)
        artifacts.append(archive)
        pkgbuild = shutil.which("pkgbuild")
        if pkgbuild:
            package = output_dir / f"{artifact_base}.pkg"
            _run(
                pkgbuild,
                "--component",
                str(application),
                "--install-location",
                "/Applications",
                "--identifier",
                "io.github.transit2fog.app",
                "--version",
                version,
                str(package),
            )
            artifacts.append(package)
    else:
        bundle = stage_dir / "Transit2Fog"
        executable_name = "Transit2Fog.exe" if os.name == "nt" else "Transit2Fog"
        executable = bundle / executable_name
        if not executable.is_file():
            raise SystemExit("PyInstaller 没有生成 Transit2Fog 可执行目录。")
        _verify_base_libraries(bundle, args.with_import_tools)
        _copy_release_documents(bundle)
        if os.name == "nt":
            shutil.copy2(PROJECT_DIR / "packaging" / "install.ps1", bundle)
            shutil.copy2(PROJECT_DIR / "packaging" / "uninstall.ps1", bundle)
        if not args.no_smoke:
            _smoke_test(executable)
        if os.name == "nt":
            archive_path = shutil.make_archive(
                str(output_dir / artifact_base),
                "zip",
                root_dir=stage_dir,
                base_dir="Transit2Fog",
            )
            artifacts.append(Path(archive_path))
            if args.windows_installer:
                artifacts.append(
                    build_windows_installer(
                        bundle, output_dir, version, args.iscc, args.with_import_tools
                    )
                )
        else:
            archive = output_dir / f"{artifact_base}.tar.gz"
            with tarfile.open(archive, "w:gz") as stream:
                stream.add(bundle, arcname=bundle.name)
            artifacts.append(archive)

    for artifact in artifacts:
        _write_checksum(artifact)
    return artifacts


def build_windows_installer(
    bundle: Path,
    output: Path,
    version: str,
    iscc: Path | None = None,
    with_import_tools: bool = False,
) -> Path:
    compiler = str(iscc) if iscc else shutil.which("ISCC")
    if compiler is None:
        for directory in ("ProgramFiles(x86)", "ProgramFiles"):
            candidate = (
                Path(os.environ.get(directory, "C:/Program Files"))
                / "Inno Setup 6"
                / "ISCC.exe"
            )
            if candidate.is_file():
                compiler = str(candidate)
                break
    if compiler is None:
        raise SystemExit("Windows 安装器需要 Inno Setup 6；可使用 --iscc 指定编译器。")
    _run(
        compiler,
        f"/DVersion={version}",
        f"/DWithImportTools={int(with_import_tools)}",
        f"/DBundleDir={bundle.resolve()}",
        f"/DOutputDir={output.resolve()}",
        str(PROJECT_DIR / "packaging" / "windows.iss"),
    )
    result = output / f"Transit2Fog-{version}-windows-x64-Setup.exe"
    if not result.is_file():
        raise SystemExit("Inno Setup 未生成安装器。")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Transit2Fog install packages")
    parser.add_argument(
        "--output",
        type=Path,
        default=RELEASE_DIR / "packages",
        help="artifact directory",
    )
    parser.add_argument("--sidecar-jar", type=Path)
    parser.add_argument(
        "--with-import-tools",
        action="store_true",
        help="Include legacy Shapefile/GDAL import dependencies (larger advanced build)",
    )
    parser.add_argument(
        "--rail-components",
        action="store_true",
        help="Publish the JAR/JRE separately and embed a pinned download manifest",
    )
    parser.add_argument(
        "--release-tag",
        help="Exact future/published release tag for component downloads",
    )
    parser.add_argument("--windows-installer", action="store_true")
    parser.add_argument("--iscc", type=Path)
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()
    artifacts = build_package(args)
    for artifact in artifacts:
        print(f"Built {artifact}")


if __name__ == "__main__":
    main()
