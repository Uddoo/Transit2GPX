#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  if [[ -n "${backend_pid:-}" ]]; then
    kill "$backend_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$project_dir/backend"
TRANSIT2FOG_ENVIRONMENT=development uv run python -m app &
backend_pid=$!

cd "$project_dir/frontend"
npm run dev
