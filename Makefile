.PHONY: doctor doctor-rail setup dev dev-rail build start start-rail package check backend-check frontend-check test e2e db-upgrade backup validate-real-data rail-bootstrap rail-fixture rail-fixture-start rail-fixture-smoke rail-yangtze-data rail-yangtze-graph rail-yangtze-start rail-yangtze-validate rail-yangtze-activate rail-china-data rail-china-graph rail-china-start rail-china-validate rail-china-activate rail-rollback clean

RAIL_GRAPH_ROOT ?= $(CURDIR)/data/rail-routing/graphs
PROJECT_TASK = uv run --project backend python scripts/project.py

doctor:
	./scripts/doctor.sh

doctor-rail:
	./scripts/doctor.sh --rail

setup:
	$(PROJECT_TASK) setup

dev:
	$(PROJECT_TASK) dev

dev-rail:
	RAIL_GRAPH_ROOT="$(RAIL_GRAPH_ROOT)" $(PROJECT_TASK) dev --rail

build:
	$(PROJECT_TASK) build

start:
	$(PROJECT_TASK) start

start-rail:
	RAIL_GRAPH_ROOT="$(RAIL_GRAPH_ROOT)" $(PROJECT_TASK) start --rail

package:
	$(PROJECT_TASK) package $(if $(SIDECAR_JAR),--sidecar-jar "$(SIDECAR_JAR)",)

check:
	$(PROJECT_TASK) check

backend-check:
	$(PROJECT_TASK) backend-check

frontend-check:
	$(PROJECT_TASK) frontend-check

test:
	$(PROJECT_TASK) test

e2e:
	$(PROJECT_TASK) e2e

db-upgrade:
	$(PROJECT_TASK) db-upgrade

backup:
	$(PROJECT_TASK) backup --output transit2fog-backup.zip

validate-real-data:
	@test -n "$(CPTOND_DIR)" || (echo "请设置 CPTOND_DIR=/absolute/path" && exit 2)
	$(PROJECT_TASK) validate-real-data --cptond-dir "$(CPTOND_DIR)"

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
