# -*- mode: python ; coding: utf-8 -*-

import json
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_dir = Path(SPECPATH).resolve().parent
backend_dir = project_dir / "backend"
package_version = json.loads(
    (project_dir / "frontend" / "package.json").read_text(encoding="utf-8")
)["version"]

datas = collect_data_files(
    "pyogrio",
    includes=["gdal_data/**", "proj_data/**"],
) + [
    (str(project_dir / "frontend" / "dist"), "frontend/dist"),
    (str(backend_dir / "migrations"), "backend/migrations"),
    (str(backend_dir / "alembic.ini"), "backend"),
    (str(backend_dir / "app" / "exports" / "gpx.xsd"), "app/exports"),
    (str(project_dir / "rail-routing" / "config.yml"), "rail-routing"),
    (str(project_dir / "rail-routing" / "versions.env"), "rail-routing"),
    (str(project_dir / "rail-routing" / "custom_models"), "rail-routing/custom_models"),
    (str(project_dir / "LICENSE"), "licenses"),
    (str(project_dir / "NOTICE"), "licenses"),
    (str(project_dir / "ATTRIBUTION.md"), "licenses"),
]
sidecar_jar = os.environ.get("TRANSIT2FOG_PACKAGE_SIDECAR_JAR")
if sidecar_jar:
    jar_path = Path(sidecar_jar).resolve()
    if not jar_path.is_file():
        raise SystemExit(f"Sidecar JAR does not exist: {jar_path}")
    datas.append((str(jar_path), "rail-routing"))
    notice_paths = json.loads(
        os.environ.get("TRANSIT2FOG_PACKAGE_SIDECAR_NOTICES", "[]")
    )
    datas.extend(
        (
            str(Path(path)),
            f"licenses/openrailrouting/{Path(path).parent.name.lower()}",
        )
        for path in notice_paths
    )

analysis = Analysis(
    [str(project_dir / "packaging" / "entrypoint.py")],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("app") + ["pyogrio._geometry"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Transit2Fog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Transit2Fog",
)

if sys.platform == "darwin":
    application = BUNDLE(
        collection,
        name="Transit2Fog.app",
        bundle_identifier="io.github.transit2fog.app",
        info_plist={
            "CFBundleDisplayName": "Transit2Fog",
            "CFBundleShortVersionString": package_version,
            "CFBundleVersion": package_version,
            "NSHighResolutionCapable": True,
        },
    )
