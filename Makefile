.PHONY: doctor doctor-rail setup dev dev-rail build start check backend-check frontend-check test e2e db-upgrade backup validate-real-data rail-bootstrap rail-fixture rail-fixture-start rail-fixture-smoke rail-yangtze-data rail-yangtze-graph rail-yangtze-start rail-yangtze-validate rail-yangtze-activate rail-china-data rail-china-graph rail-china-start rail-china-validate rail-china-activate rail-rollback clean

RAIL_GRAPH_ROOT ?= $(CURDIR)/data/rail-routing/graphs

doctor:
	./scripts/doctor.sh

doctor-rail:
	./scripts/doctor.sh --rail

setup:
	uv sync --project backend --dev
	npm ci --prefix frontend

dev: db-upgrade
	./scripts/dev.sh

dev-rail: db-upgrade
	TRANSIT2FOG_RAIL_ENABLED=true \
	TRANSIT2FOG_RAIL_GRAPH_VERSION=active \
	TRANSIT2FOG_RAIL_GRAPH_ROOT="$(RAIL_GRAPH_ROOT)" \
	TRANSIT2FOG_RAIL_SIDECAR_URL=http://127.0.0.1:8989 \
	./scripts/dev.sh

build:
	npm run build --prefix frontend

start: build db-upgrade
	./scripts/start.sh

check:
	./scripts/check.sh

backend-check:
	uv run --project backend ruff check backend/app backend/tests backend/migrations scripts
	uv run --project backend ruff format --check backend/app backend/tests backend/migrations scripts
	uv run --project backend mypy backend/app
	uv run --project backend pytest backend/tests --cov=backend/app --cov-report=term-missing

frontend-check:
	npm run lint --prefix frontend
	npm run test --prefix frontend
	npm run build --prefix frontend

test:
	uv run --project backend pytest backend/tests
	npm run test --prefix frontend

e2e: build
	npm run test:e2e --prefix frontend

db-upgrade:
	cd backend && uv run alembic upgrade head

backup:
	uv run --project backend python scripts/backup.py transit2fog-backup.zip

validate-real-data:
	@test -n "$(CPTOND_DIR)" || (echo "请设置 CPTOND_DIR=/absolute/path" && exit 2)
	uv run --project backend python scripts/validate_cptond.py "$(CPTOND_DIR)"

rail-bootstrap:
	./scripts/rail_bootstrap.sh

rail-fixture: rail-bootstrap
	./scripts/rail_build_graph.sh "$(CURDIR)/data/rail-routing/upstream/OpenRailRouting/files/cologne-railway.osm.pbf" fixture-cologne

rail-fixture-start:
	./scripts/rail_start.sh fixture-cologne "$(CURDIR)/data/rail-routing/upstream/OpenRailRouting/files/cologne-railway.osm.pbf"

rail-fixture-smoke:
	./scripts/rail_smoke.sh

rail-yangtze-data:
	uv run --project backend python scripts/rail_prepare_region.py rail-routing/data/yangtze-20260815.json data/rail-routing/regions

rail-yangtze-graph: rail-bootstrap rail-yangtze-data
	RAIL_SOURCE_URL=https://download.geofabrik.de/asia/china.html \
	RAIL_SOURCE_TIMESTAMP=2026-08-15T22:41:00Z \
	RAIL_EXTRACT_REGION=Shanghai+Jiangsu+Zhejiang+Anhui \
	./scripts/rail_build_graph.sh "$(CURDIR)/data/rail-routing/regions/yangtze-20260815/yangtze-20260815.osm.pbf" yangtze-20260815-r0.1

rail-yangtze-start:
	RAIL_GRAPH_ROOT="$(RAIL_GRAPH_ROOT)" \
	./scripts/rail_start.sh yangtze-20260815-r0.1 \
		"$(CURDIR)/data/rail-routing/regions/yangtze-20260815/yangtze-20260815.osm.pbf"

rail-yangtze-validate:
	uv run --project backend python scripts/rail_validate_routes.py \
		rail-routing/data/yangtze-acceptance-routes.json \
		--output data/rail-routing/regions/yangtze-20260815/route-validation.json

rail-yangtze-activate: rail-yangtze-validate
	uv run --project backend python scripts/rail_activate_graph.py \
		--graph-root "$(RAIL_GRAPH_ROOT)" activate yangtze-20260815-r0.1 \
		--validation-report data/rail-routing/regions/yangtze-20260815/route-validation.json

rail-china-data:
	uv run --project backend python scripts/rail_prepare_region.py rail-routing/data/china-20260815.json data/rail-routing/regions

rail-china-graph: rail-bootstrap rail-china-data
	RAIL_SOURCE_URL=https://download.geofabrik.de/asia/china.html \
	RAIL_SOURCE_TIMESTAMP=2026-08-15T22:38:00Z \
	RAIL_EXTRACT_REGION=China \
	./scripts/rail_build_graph.sh "$(CURDIR)/data/rail-routing/regions/china-20260815/china-20260815.osm.pbf" china-20260815-r3.1

rail-china-start:
	RAIL_GRAPH_ROOT="$(RAIL_GRAPH_ROOT)" \
	./scripts/rail_start.sh china-20260815-r3.1 \
		"$(CURDIR)/data/rail-routing/regions/china-20260815/china-20260815.osm.pbf"

rail-china-validate:
	uv run --project backend python scripts/rail_validate_routes.py \
		rail-routing/data/china-acceptance-routes.json \
		--output data/rail-routing/regions/china-20260815/route-validation.json

rail-china-activate: rail-china-validate
	uv run --project backend python scripts/rail_activate_graph.py \
		--graph-root "$(RAIL_GRAPH_ROOT)" activate china-20260815-r3.1 \
		--validation-report data/rail-routing/regions/china-20260815/route-validation.json

rail-rollback:
	uv run --project backend python scripts/rail_activate_graph.py \
		--graph-root "$(RAIL_GRAPH_ROOT)" rollback

clean:
	uv clean
	rm -rf frontend/dist frontend/playwright-report frontend/test-results
