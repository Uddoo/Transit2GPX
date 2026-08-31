#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uv run --project "$project_dir/backend" python "$project_dir/scripts/project.py" start
