---
name: transit2fog-validation
description: Validate Transit2Fog changes to route import, candidate confirmation, journey persistence, GPX exports, API contracts, map state, or railway sidecar behavior. Select focused regressions and preserve project business invariants. Use for related implementation or review and release verification, not unrelated documentation or general GIS analysis.
---

# Transit2Fog validation

Resolve project paths from the repository root (three levels above this skill).
Use this workflow to select checks for the requested change; it does not authorize
commits, publishing, real-data replacement, or unrelated architectural changes.

## Establish the contract

Read the relevant sections of `docs/DATA_API.md` and `docs/DECISIONS.md` before
changing domain behavior. Consult `docs/ARCHITECTURE.md` for module boundaries,
`docs/DEVELOPMENT.md` and `scripts/project.py` for current check commands, and
`docs/RAILWAY.md` only for railway changes. Treat the current source and tests as
implementation evidence; surface material conflicts with the documented contract.

Keep React/Vite/Leaflet, FastAPI, synchronous SQLAlchemy/SQLite and the optional
Java sidecar unless the user requested architectural work. Use the installed
`geopandas` and `tanstack-query` skills where applicable. Reuse available
`build-web-apps:react-best-practices`, `build-web-apps:frontend-testing-debugging`
and `playwright` for their focused tasks; do not require additional installations.

## Business invariants

- **Coordinate boundary:** WKB/Shapely/GeoJSON use WGS-84 `(lon, lat)`;
  Leaflet alone takes `(lat, lon)`; GPX uses named `lat`/`lon` attributes.
  Length, projection, cutting and densification use local AEQD metres.
- **Actual route:** preserve route variants, loop direction, branch identity,
  ordered via stations and reversed edges. Ambiguity requires candidate review;
  a shortest route does not prove the user's trip. Blocked quality cannot become
  `resolved` merely because there is one candidate.
- **Confirmation:** candidate ID/digest and dataset identity are checked by the
  server before transactional persistence. The frontend cannot supply arbitrary
  rail geometry or silently confirm a candidate through optimistic cache updates.
- **One path fact:** metro legs use ordered `journey_leg_edge` references;
  railway legs use immutable `rail_journey_edge_snapshot` geometry. Preview,
  reopening and export consume confirmed facts, never a fresh routing result.
  GraphHopper internal edge IDs are not durable identity. Recalculation creates
  a new journey and leaves original snapshots unchanged.
- **GPX:** validate GPX 1.1 against `backend/app/exports/gpx.xsd`. Do not fabricate
  point times, elevations or speeds. Preserve the distinction between journeys
  and coverage; split discontinuities into separate `trkseg` elements. Railway
  coverage deduplication is bounded by data/graph version; preserve warnings and
  source attribution. Downloads must honor the matching valid preview digest.
- **Data/UI:** activation follows successful import quality checks; old ready
  data stays available during staging. Empty/unready/failed map responses show
  real status, never decorative route geometry. Invalidate relevant client caches
  after mutations without losing explicit user confirmation state.
- **Rail isolation:** unavailable Java/graph/sidecar disables rail routing only;
  metro-only startup and workflows still work. Keep loopback binding, graph/PBF/
  Profile identity checks and supervisor process ownership boundaries. Previously
  confirmed rail snapshots remain exportable without the old sidecar.

## Choose proportional verification

Use small synthetic fixtures and existing temporary-database test infrastructure.
Do not point migrations, imports or activation checks at a user's database as a
test convenience. Inspect fixture setup before introducing a new integration test.

Commands below run from the repository root in PowerShell 7. Recheck file names
and command definitions when the checkout changes. Select affected tests first;
full checks are appropriate for broad changes or a requested release verification.

| Change | Existing regression entry points |
|---|---|
| Import, coordinates, topology | `backend/tests/test_cptond_importer.py`, `test_geometry_edges.py`, `test_routing_topologies.py` |
| Journey, candidate, CSV, GPX | `backend/tests/test_journey_export_api.py`, `test_csv_import_api.py`, `test_providers.py` |
| Railway lifecycle | `backend/tests/test_sidecar_supervisor.py`, `test_rail_sidecar_compatibility.py`, `test_rail_activation.py`, `test_rail_data_api.py` |
| Schema/storage | `backend/tests/test_schema.py`, `test_migrations.py`, `test_backup_restore.py` |
| API schema | Generate OpenAPI/types when changed, then check drift and frontend consumers |
| React/cache/map interactions | Related Vitest tests, then browser/fullstack scenarios for changed user flows |

Example focused geometry check:

```powershell
uv run --project backend python -m pytest backend/tests/test_geometry_edges.py backend/tests/test_routing_topologies.py
```

Existing aggregate commands:

```powershell
.\transit2fog.ps1 backend-check
.\transit2fog.ps1 frontend-check
.\transit2fog.ps1 check
.\transit2fog.ps1 e2e
```

Choose the relevant command; do not run all overlapping aggregates in sequence.
`check` includes backend lint/type/tests/coverage and frontend API drift, lint,
coverage and production build. `e2e` builds and runs both mocked-browser and
isolated real-fullstack flows. A mocked UI pass alone is not API/GPX proof.

For API schema edits:

```powershell
npm run api:generate --prefix frontend
npm run api:check --prefix frontend
```

Review both `frontend/openapi.json` and `frontend/src/api/generated.ts`; do not
hand-edit generated types. Railway fixture verification and packaging have
separate data/runtime prerequisites: inspect `docs/WINDOWS.md`,
`docs/PACKAGING.md` and the relevant script before invoking them. Skill-only or
documentation-only edits do not require running application suites.

## Report evidence

State the affected invariant, checks actually run and results, plus any untested
runtime/data prerequisite. Keep synthetic tests, real-data validation, package
smoke tests and external Fog of World device acceptance distinct. Use
`docs/FOG_ACCEPTANCE.md` / `docs/RAIL_FOG_ACCEPTANCE.md` for requested device
acceptance; generated GPX alone does not establish successful device import.
