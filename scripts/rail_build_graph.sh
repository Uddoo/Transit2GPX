#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 /absolute/path/region.osm.pbf graph-version" >&2
  exit 2
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_dir/rail-routing/versions.env"

pbf_dir="$(cd "$(dirname "$1")" && pwd)"
pbf_path="$pbf_dir/$(basename "$1")"
graph_version="$2"
if [[ ! -f "$pbf_path" ]]; then
  echo "PBF does not exist: $pbf_path" >&2
  exit 2
fi
if [[ "$pbf_path" != *.osm.pbf ]]; then
  echo "Expected a .osm.pbf input: $pbf_path" >&2
  exit 2
fi
if [[ ! "$graph_version" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Graph version may contain only letters, numbers, dot, underscore, and dash." >&2
  exit 2
fi

work_dir="${RAIL_WORK_DIR:-$project_dir/data/rail-routing}"
graph_root="${RAIL_GRAPH_ROOT:-$work_dir/graphs}"
jar_path="$work_dir/dist/openrailrouting.jar"
config_path="$project_dir/rail-routing/config.yml"
final_graph="$graph_root/$graph_version"

if [[ ! -f "$jar_path" ]]; then
  echo "Missing sidecar JAR. Run ./scripts/rail_bootstrap.sh first." >&2
  exit 3
fi
if [[ -e "$final_graph" ]]; then
  echo "Refusing to overwrite existing graph version: $final_graph" >&2
  exit 4
fi

mkdir -p "$graph_root"
temporary_graph="$(mktemp -d "$graph_root/.${graph_version}.XXXXXX")"
cleanup() {
  if [[ -n "${temporary_graph:-}" && -d "$temporary_graph" ]]; then
    rm -rf "$temporary_graph"
  fi
}
trap cleanup EXIT INT TERM
read -r -a java_opts <<< "${RAIL_JAVA_OPTS:--Xms256m -Xmx2500m}"
if [[ -n "${RAIL_JAVA_HOME:-}" ]]; then
  java_bin="$RAIL_JAVA_HOME/bin/java"
  if [[ ! -x "$java_bin" ]]; then
    echo "RAIL_JAVA_HOME does not contain an executable bin/java: $RAIL_JAVA_HOME" >&2
    exit 2
  fi
else
  java_bin="$(command -v java)"
fi

(
  cd "$project_dir/rail-routing"
  "$java_bin" "${java_opts[@]}" \
    -Ddw.graphhopper.datareader.file="$pbf_path" \
    -Ddw.graphhopper.graph.location="$temporary_graph" \
    -jar "$jar_path" import "$config_path"
)

mv "$temporary_graph" "$final_graph"
temporary_graph=""

pbf_sha256="$(shasum -a 256 "$pbf_path" | awk '{print $1}')"
python3 - "$final_graph/transit2fog-graph.json" "$graph_version" "$pbf_sha256" \
  "$OPENRAILROUTING_COMMIT" "$GRAPHHOPPER_FORK_VERSION" "$RAIL_PROFILE_VERSION" \
  "$(basename "$pbf_path")" "${RAIL_SOURCE_URL:-}" "${RAIL_SOURCE_TIMESTAMP:-}" \
  "${RAIL_EXTRACT_REGION:-}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    output,
    graph_version,
    pbf_sha256,
    openrail_commit,
    graphhopper_version,
    profile_version,
    pbf_filename,
    source_url,
    source_timestamp,
    extract_region,
) = sys.argv[1:]
payload = {
    "graph_version": graph_version,
    "pbf_filename": pbf_filename,
    "pbf_sha256": pbf_sha256,
    "source_url": source_url or None,
    "source_timestamp": source_timestamp or None,
    "extract_region": extract_region or None,
    "openrailrouting_commit": openrail_commit,
    "graphhopper_version": graphhopper_version,
    "profile_version": profile_version,
    "license": "ODbL-1.0",
    "built_at": datetime.now(timezone.utc).isoformat(),
}
Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

echo "Rail graph '$graph_version' is ready at $final_graph"
