from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import case, func, select

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a real CPTOND v2 or compatible Science Data Bank "
            "timeline directory in an isolated database"
        )
    )
    parser.add_argument("directory", type=Path, help="Extracted CPTOND directory")
    parser.add_argument(
        "--runtime",
        type=Path,
        help="Keep the validation database in this directory instead of a temp dir",
    )
    parser.add_argument("--source-version", default="v2-real-validation")
    args = parser.parse_args()

    temporary = None
    if args.runtime is None:
        temporary = tempfile.TemporaryDirectory(prefix="metro2fog-real-validation-")
        runtime = Path(temporary.name)
    else:
        runtime = args.runtime.expanduser().resolve()
        runtime.mkdir(parents=True, exist_ok=True)
    database = runtime / "validation.sqlite3"
    os.environ["METRO2FOG_ENVIRONMENT"] = "test"
    os.environ["METRO2FOG_DATA_DIR"] = str(runtime)
    os.environ["METRO2FOG_DATABASE_URL"] = f"sqlite:///{database}"

    from app.db.base import Base
    from app.db.models import City, DatasetVersion, Line, RouteVariant
    from app.db.search import ensure_search_indexes
    from app.db.session import SessionLocal, engine
    from app.importers.cptond import (
        audit_dataset,
        create_dataset_import,
        run_dataset_import,
    )

    first_audit = audit_dataset(args.directory)
    second_audit = audit_dataset(args.directory)
    if first_audit != second_audit:
        raise SystemExit("重复审计结果不一致，不能继续验收。")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_search_indexes(connection)
    handle = create_dataset_import(first_audit, args.source_version)
    if handle.should_run:
        run_dataset_import(handle.import_id, first_audit)

    with SessionLocal() as db:
        dataset = db.get(DatasetVersion, handle.import_id)
        if dataset is None or dataset.status != "ready":
            error = dataset.error_message if dataset is not None else "任务不存在"
            raise SystemExit(f"真实数据导入未通过：{error}")
        rows = db.execute(
            select(
                City.id,
                City.name_cn,
                func.count(RouteVariant.id).label("variants"),
                func.sum(case((RouteVariant.is_loop.is_(True), 1), else_=0)).label(
                    "loops"
                ),
                func.sum(case((RouteVariant.is_branch.is_(True), 1), else_=0)).label(
                    "branches"
                ),
            )
            .join(Line, Line.city_id == City.id)
            .join(RouteVariant, RouteVariant.line_id == Line.id)
            .where(
                City.dataset_version_id == dataset.id,
                City.status == "ready",
                Line.status == "ready",
                RouteVariant.quality_status == "ready",
            )
            .group_by(City.id, City.name_cn)
            .order_by(City.name_cn)
        ).all()
        city_reports = [
            {
                "city_id": city_id,
                "name": name,
                "ready_variants": int(variants),
                "loop_variants": int(loops or 0),
                "branch_variants": int(branches or 0),
            }
            for city_id, name, variants, loops, branches in rows
        ]
        ordinary = next(
            (
                city
                for city in city_reports
                if city["loop_variants"] == 0 and city["branch_variants"] == 0
            ),
            None,
        )
        complex_city = next(
            (
                city
                for city in city_reports
                if city["loop_variants"] > 0 or city["branch_variants"] > 0
            ),
            None,
        )
        if ordinary is None or complex_city is None or ordinary == complex_city:
            raise SystemExit("没有同时找到普通线路城市和环线/支线城市。")
        report = {
            "result": "ready_for_manual_map_sampling",
            "runtime": str(runtime) if args.runtime is not None else None,
            "dataset_version_id": dataset.id,
            "source_format": first_audit.source_format,
            "source_url": dataset.source_url,
            "license": dataset.license,
            "checksum": dataset.checksum,
            "route_count": dataset.route_count,
            "stop_count": dataset.stop_count,
            "processed_cities": dataset.processed_cities,
            "ready_lines": dataset.ready_lines,
            "blocked_lines": dataset.blocked_lines,
            "ordinary_city": ordinary,
            "complex_city": complex_city,
            "cities": city_reports,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if temporary is not None:
        temporary.cleanup()


if __name__ == "__main__":
    main()
