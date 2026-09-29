#!/usr/bin/env bash
set -euo pipefail

base_url="${RAIL_SIDECAR_URL:-http://127.0.0.1:8989}"
profile="${RAIL_SMOKE_PROFILE:-china_conventional}"
from_lat="${RAIL_SMOKE_FROM_LAT:-50.85139337895494}"
from_lon="${RAIL_SMOKE_FROM_LON:-6.908898310661318}"
to_lat="${RAIL_SMOKE_TO_LAT:-50.94193447111784}"
to_lon="${RAIL_SMOKE_TO_LON:-6.960010517835617}"
response_file="$(mktemp -t transit2gpx-rail-smoke.XXXXXX)"
trap 'rm -f "$response_file"' EXIT INT TERM

ready=0
for _attempt in $(seq 1 30); do
  if curl --fail --silent "$base_url/info" >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  echo "Rail sidecar did not become ready at $base_url." >&2
  exit 3
fi

curl --fail --silent --show-error --get "$base_url/route" \
  --data-urlencode "point=$from_lat,$from_lon" \
  --data-urlencode "point=$to_lat,$to_lon" \
  --data-urlencode "profile=$profile" \
  --data-urlencode "points_encoded=false" \
  --data-urlencode "instructions=false" \
  --data-urlencode "details=osm_way_id" \
  --output "$response_file"

python3 - "$response_file" "$profile" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("message"):
    raise SystemExit(f"rail route failed: {payload['message']}")
paths = payload.get("paths") or []
if not paths:
    raise SystemExit("rail route response contains no path")
path = paths[0]
coordinates = path.get("points", {}).get("coordinates") or []
if len(coordinates) < 2 or float(path.get("distance", 0)) <= 0:
    raise SystemExit("rail route has invalid distance or geometry")
print(
    f"rail smoke passed: profile={sys.argv[2]} "
    f"distance_m={path['distance']:.1f} points={len(coordinates)}"
)
PY
