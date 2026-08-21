.PHONY: setup dev build start check backend-check frontend-check test e2e db-upgrade backup validate-real-data clean

setup:
	uv sync --project backend --dev
	npm ci --prefix frontend

dev: db-upgrade
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
	uv run --project backend python scripts/backup.py metro2fog-backup.zip

validate-real-data:
	@test -n "$(CPTOND_DIR)" || (echo "请设置 CPTOND_DIR=/absolute/path" && exit 2)
	uv run --project backend python scripts/validate_cptond.py "$(CPTOND_DIR)"

clean:
	uv clean
	rm -rf frontend/dist frontend/playwright-report frontend/test-results
