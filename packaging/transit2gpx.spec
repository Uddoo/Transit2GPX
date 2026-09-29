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

with_import_tools = os.environ.get("TRANSIT2GPX_PACKAGE_IMPORT_TOOLS") == "1"
datas = (collect_data_files(
    "pyogrio",
    includes=["gdal_data/**", "proj_data/**"],
) if with_import_tools else []) + [
    (str(project_dir / "frontend" / "dist"), "frontend/dist"),
    (str(project_dir / "city-data" / "catalog.json"), "city-data"),
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
sidecar_jar = os.environ.get("TRANSIT2GPX_PACKAGE_SIDECAR_JAR")
component_manifest = os.environ.get("TRANSIT2GPX_PACKAGE_COMPONENT_MANIFEST")
if component_manifest:
    datas.append((component_manifest, "rail-routing"))
if sidecar_jar:
    jar_path = Path(sidecar_jar).resolve()
    if not jar_path.is_file():
        raise SystemExit(f"Sidecar JAR does not exist: {jar_path}")
    datas.append((str(jar_path), "rail-routing"))
    notice_paths = json.loads(
        os.environ.get("TRANSIT2GPX_PACKAGE_SIDECAR_NOTICES", "[]")
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
    hiddenimports=collect_submodules("app", filter=lambda name: with_import_tools or name != "app.importers.cptond") + (["pyogrio._geometry"] if with_import_tools else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff"] + ([] if with_import_tools else ["geopandas", "pandas", "pyogrio", "app.importers.cptond"]),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Transit2GPX",
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
    name="Transit2GPX",
)

if sys.platform == "darwin":
    application = BUNDLE(
        collection,
        name="Transit2GPX.app",
        bundle_identifier="io.github.transit2fog.app",
        info_plist={
            "CFBundleDisplayName": "Transit2GPX",
            "CFBundleShortVersionString": package_version,
            "CFBundleVersion": package_version,
            "NSHighResolutionCapable": True,
        },
    )
