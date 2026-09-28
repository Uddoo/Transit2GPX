# Railway routing sidecar

This directory contains only the reproducible configuration for Transit2Fog's
optional OpenRailRouting sidecar. PBF files, Maven, the upstream checkout, the
built JAR, graph caches, and responses stay under the ignored `data/` tree.

The OpenRailRouting and Geofabrik GraphHopper fork source commits and build
versions are locked in `versions.env`. The fork is built locally because its
custom artifacts are not available from Maven Central. The sidecar binds only
to `127.0.0.1`; FastAPI remains the only API intended for the frontend.

## Local fixture proof

Java 17 or newer, Git, `curl`, `tar`, and `python3` are required. Maven is
downloaded into the ignored work directory and verified with SHA-512.
Set `RAIL_JAVA_HOME` when the system default Java is not the version intended
for a reproducible build; Java 21 is the currently verified runtime.

The commands below use the macOS Makefile form. On Windows PowerShell 7, use
the same target name after `.\transit2fog.ps1`; for example,
`.\transit2fog.ps1 doctor-rail` and `.\transit2fog.ps1 rail-bootstrap`.
The Windows bootstrap uses `mvn.cmd`, `git apply`, native archive/hash APIs,
and does not require WSL, Git Bash, GNU Make, `patch`, or `shasum`.
`.\transit2fog.ps1 setup-java` installs the pinned project-local Temurin 21
archive after SHA-256 verification without changing system environment
variables. `.\transit2fog.ps1 rail-fixture-verify` starts the fixture sidecar,
checks routing and both metadata endpoints, and then verifies port cleanup.

Run the preflight check before downloading or building anything:

```sh
make doctor-rail
```

```sh
make rail-bootstrap
make rail-fixture
```

Start the fixture sidecar in terminal A:

```sh
make rail-fixture-start
```

Then verify the HTTP route response in another terminal:

```sh
make rail-fixture-smoke
```

## Reproducible Yangtze Delta acceptance

The pinned regional manifest downloads and verifies the 2026-08-15 Shanghai,
Jiangsu, Zhejiang, and Anhui Geofabrik extracts before atomically merging them.
Build the immutable graph, then use two terminals once to start, validate, and
activate the new graph:

```sh
make rail-yangtze-data
make rail-yangtze-graph

# Terminal A
make rail-yangtze-start

# Terminal B
make rail-yangtze-activate
```

After activation, stop terminal A. Daily development or production uses the
managed sidecar in the same process tree:

```sh
make dev-rail
make start-rail
```

The validator rejects missing China profiles, invalid WGS-84 geometry,
discontinuous OSM way ranges, station snapping over 2 km, and implausible route
lengths. Its timestamped result is written beneath the ignored dataset folder.

## Build a real regional graph

Download or prepare a versioned `.osm.pbf`, record its provider timestamp, and
build it into a new immutable graph directory:

```sh
./scripts/rail_build_graph.sh /absolute/path/region.osm.pbf region-YYYYMMDD
./scripts/rail_start.sh region-YYYYMMDD /absolute/path/region.osm.pbf
```

Windows equivalent:

```powershell
.\transit2fog.ps1 rail-build-graph `
  -PbfPath 'D:\Rail\region.osm.pbf' `
  -GraphVersion 'region-YYYYMMDD'
```

The build refuses to overwrite an existing version. A successful import is
first created in a temporary sibling directory and moved into place only after
OpenRailRouting exits successfully.

## Nationwide graph, validation, and activation

The pinned China manifest, immutable build metadata, and eight-route acceptance
set are tracked under `rail-routing/data/`. Large PBF, graph, database, and
validation outputs remain ignored. Build first, then use two terminals once for
validation and activation:

```sh
make rail-china-data
make rail-china-graph

# Terminal A
make rail-china-start

# Terminal B
make rail-china-activate
```

After activation, `make dev-rail` or `make start-rail` starts and supervises the
identity-checked sidecar automatically. Activation refuses a report whose graph/PBF/Profile/commit identity differs
from the immutable graph metadata. New activations atomically update
`active.json` and `previous.json`, whose values are restricted to a safe,
single graph-version name. Existing safe relative `active` and `previous`
symlinks remain supported for compatibility. The JSON form avoids Windows
symlink privilege requirements. Roll back to the previously validated graph with:

```sh
make rail-rollback
```

Run FastAPI with `TRANSIT2FOG_RAIL_GRAPH_VERSION=active`; the resolver follows
the selector to the immutable graph version and verifies the running sidecar's
four-part identity before every route calculation. Old journey snapshots do
not require the old sidecar to reopen or export.

New graphs use `transit2fog-graph.json` and the sidecar exposes
`/transit2fog/metadata`. Existing `metro2fog-graph.json` files and the legacy
`/metro2fog/metadata` endpoint remain readable during the product-name migration.

The 2026-08-21 reference build used a 1,579,509,099-byte China PBF and produced
a 186,698,828-byte graph with 645,361 nodes and 742,281 edges. Import took
165.55 seconds with peak RSS 1,456,046,080 bytes on the acceptance machine.
The eight-route validation median was 16.014 ms and p95/max was 17.127 ms.
These are reproducibility observations, not universal minimum requirements.

The three R0 profiles are deliberately preferences rather than claims about a
train's exact path:

- `china_high_speed`: favors fast, electrified main lines.
- `china_emu`: favors electrified passenger main lines with a 250 km/h cap.
- `china_conventional`: permits conventional main lines with a 160 km/h cap.

Missing OSM speed or electrification tags are not hard failures. Yard, spur,
siding, and crossover tracks are excluded or strongly penalized. Later route
candidate scoring and user confirmation remain mandatory.

## Data and licensing

OpenRailRouting is Apache-2.0. OpenStreetMap extracts are ODbL; any user-facing
railway map or route result must display `© OpenStreetMap contributors`. Do not
commit PBF files, graph caches, or derived national railway databases to this
repository. See `../ATTRIBUTION.md` and `../docs/RAILWAY.md`.
