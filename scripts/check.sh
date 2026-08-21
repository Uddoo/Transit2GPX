#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

uv run --project "$project_dir/backend" ruff check "$project_dir/backend/app" "$project_dir/backend/tests" "$project_dir/backend/migrations" "$project_dir/scripts"
uv run --project "$project_dir/backend" ruff format --check "$project_dir/backend/app" "$project_dir/backend/tests" "$project_dir/backend/migrations" "$project_dir/scripts"
uv run --project "$project_dir/backend" mypy "$project_dir/backend/app"
uv run --project "$project_dir/backend" pytest "$project_dir/backend/tests" --cov="$project_dir/backend/app" --cov-report=term-missing

npm run lint --prefix "$project_dir/frontend"
npm run test --prefix "$project_dir/frontend"
npm run build --prefix "$project_dir/frontend"
