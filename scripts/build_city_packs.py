"""Build standard city packs from an isolated raw import or a read-only database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build .t2fcity standard city packages"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--database", type=Path, help="Read-only validated Transit2GPX database"
    )
    source.add_argument(
        "--raw-directory",
        type=Path,
        help="Raw CPTOND data; requires import-tools dependency group",
    )
    parser.add_argument(
        "--city-code",
        action="append",
        help="Repeat to select cities; default all ready cities",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-version", default="citypack-source-v1")
    parser.add_argument(
        "--attribution",
        help="Original attribution text; defaults to source name, license and URL",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="transit2gpx-city-builder-") as temporary:
        if args.raw_directory:
            os.environ["TRANSIT2GPX_DATA_DIR"] = temporary
            os.environ["TRANSIT2GPX_DATABASE_URL"] = (
                f"sqlite:///{Path(temporary) / 'build.sqlite3'}"
            )
            from app.db.base import Base
            from app.db.search import ensure_search_indexes
            from app.db.session import engine as build_engine
            from app.importers.cptond import (
                audit_dataset,
                create_dataset_import,
                run_dataset_import,
            )

            audit = audit_dataset(args.raw_directory)
            Base.metadata.create_all(build_engine)
            with build_engine.begin() as connection:
                ensure_search_indexes(connection)
            handle = create_dataset_import(audit, args.source_version)
            run_dataset_import(handle.import_id, audit)
            database = Path(temporary) / "build.sqlite3"
        else:
            database = args.database.resolve()
            if not database.is_file():
                raise SystemExit("源数据库不存在。")
        from app.db.active_cities import current_city_ids
        from app.db.models import City, DatasetVersion
        from app.importers.city_pack import export_city_pack
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        engine = create_engine(
            f"sqlite:///file:{quote(database.as_posix(), safe='/:')}?mode=ro&uri=true"
        )
        try:
            with Session(engine) as db:
                query = (
                    select(City)
                    .where(City.id.in_(current_city_ids()))
                    .order_by(City.source_city_code)
                )
                if args.city_code:
                    query = query.where(City.source_city_code.in_(args.city_code))
                cities = db.scalars(query).all()
                if not cities or (
                    args.city_code
                    and set(args.city_code)
                    != {city.source_city_code for city in cities}
                ):
                    raise SystemExit("没有找到全部指定的可用城市。")
                args.output.mkdir(parents=True, exist_ok=True)
                catalogue = []
                for city in cities:
                    dataset = db.get(DatasetVersion, city.dataset_version_id)
                    assert dataset is not None
                    attribution = (
                        args.attribution
                        or f"{dataset.source_name}; {dataset.license}; {dataset.source_url}"
                    )
                    filename = f"city-{hashlib.sha256(city.source_city_code.encode()).hexdigest()[:12]}.t2fcity"
                    path = args.output / filename
                    preview = export_city_pack(db, city.id, path, attribution)
                    catalogue.append(
                        {
                            "file": filename,
                            "size": path.stat().st_size,
                            **preview.model_dump(),
                        }
                    )
                (args.output / "index.json").write_text(
                    json.dumps(catalogue, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(
                    f"Built {len(catalogue)} city packages in {args.output.resolve()}"
                )
        finally:
            engine.dispose()
            if args.raw_directory:
                build_engine.dispose()


if __name__ == "__main__":
    main()
