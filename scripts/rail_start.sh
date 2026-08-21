#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 graph-version /absolute/path/region.osm.pbf" >&2
  exit 2
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="${RAIL_WORK_DIR:-$project_dir/data/rail-routing}"
graph_root="${RAIL_GRAPH_ROOT:-$work_dir/graphs}"
requested_graph_version="$1"
pbf_dir="$(cd "$(dirname "$2")" && pwd)"
pbf_path="$pbf_dir/$(basename "$2")"
graph_path="$graph_root/$requested_graph_version"
jar_path="$work_dir/dist/openrailrouting.jar"
config_path="$project_dir/rail-routing/config.yml"
application_port="${RAIL_SIDECAR_PORT:-8989}"
admin_port="${RAIL_SIDECAR_ADMIN_PORT:-8990}"

if [[ ! -f "$jar_path" ]]; then
  echo "Missing sidecar JAR. Run ./scripts/rail_bootstrap.sh first." >&2
  exit 3
fi
if [[ ! -f "$pbf_path" ]]; then
  echo "PBF does not exist: $pbf_path" >&2
  exit 3
fi
metadata_path="$graph_path/transit2fog-graph.json"
if [[ ! -f "$metadata_path" ]]; then
  metadata_path="$graph_path/metro2fog-graph.json"
fi
if [[ ! -f "$metadata_path" ]]; then
  echo "Graph version is missing or incomplete: $graph_path" >&2
  exit 3
fi
if [[ "$requested_graph_version" == "active" && ! -L "$graph_path" ]]; then
  echo "The active graph selector must be a symbolic link." >&2
  exit 3
fi
if [[ "$requested_graph_version" == "active" ]]; then
  active_target="$(readlink "$graph_path")"
  if [[ "$active_target" == */* || "$active_target" == .* ]]; then
    echo "The active graph selector has an unsafe target." >&2
    exit 3
  fi
fi

graph_identity=()
while IFS= read -r value; do
  graph_identity+=("$value")
done < <(
  python3 - "$metadata_path" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in (
    "graph_version",
    "pbf_sha256",
    "profile_version",
    "openrailrouting_commit",
):
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"Graph metadata is missing {key}.")
    print(value)
PY
)
if [[ "$requested_graph_version" != "active" && "${graph_identity[0]}" != "$requested_graph_version" ]]; then
  echo "Graph metadata version does not match the selected directory." >&2
  exit 3
fi
actual_pbf_sha256="$(shasum -a 256 "$pbf_path" | awk '{print $1}')"
if [[ "$actual_pbf_sha256" != "${graph_identity[1]}" ]]; then
  echo "Selected PBF checksum does not match the graph metadata." >&2
  exit 3
fi

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
cd "$project_dir/rail-routing"
exec "$java_bin" "${java_opts[@]}" \
  -Dtransit2fog.graph.version="${graph_identity[0]}" \
  -Dtransit2fog.pbf.sha256="${graph_identity[1]}" \
  -Dtransit2fog.profile.version="${graph_identity[2]}" \
  -Dtransit2fog.openrailrouting.commit="${graph_identity[3]}" \
  -Dmetro2fog.graph.version="${graph_identity[0]}" \
  -Dmetro2fog.pbf.sha256="${graph_identity[1]}" \
  -Dmetro2fog.profile.version="${graph_identity[2]}" \
  -Dmetro2fog.openrailrouting.commit="${graph_identity[3]}" \
  -Ddw.graphhopper.datareader.file="$pbf_path" \
  -Ddw.graphhopper.graph.location="$graph_path" \
  -Ddw.server.application_connectors[0].port="$application_port" \
  -Ddw.server.admin_connectors[0].port="$admin_port" \
  -jar "$jar_path" serve "$config_path"
