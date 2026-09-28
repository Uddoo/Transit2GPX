from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def _render_schema() -> str:
    with tempfile.TemporaryDirectory(prefix="transit2fog-openapi-") as runtime:
        os.environ["TRANSIT2FOG_ENVIRONMENT"] = "test"
        os.environ["TRANSIT2FOG_DATA_DIR"] = runtime
        os.environ["TRANSIT2FOG_DATABASE_URL"] = (
            f"sqlite:///{Path(runtime, 'openapi.sqlite3').as_posix()}"
        )

        from app.main import create_app

        schema = create_app().openapi()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the FastAPI OpenAPI contract")
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the committed schema is stale",
    )
    args = parser.parse_args()
    content = _render_schema()
    output = args.output.resolve()
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != content:
            raise SystemExit(
                f"OpenAPI schema is stale: run the API generation command for {output}"
            )
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
