# Common commands. Requires Docker with Compose v2; e2e needs any Python 3.9+ on the host.
COMPOSE ?= docker compose
PYTHON ?= python3

.PHONY: up down test e2e openapi logs reset ps web-install web-dev web-test web-types

up:            ## build and start the whole stack (web on http://localhost:8080, api on http://localhost:8000/api, Swagger /api/docs)
	$(COMPOSE) up --build -d --wait
	$(COMPOSE) ps

down:          ## stop containers, keep the database volume
	$(COMPOSE) down

test:          ## pytest against a disposable PostgreSQL 17 (compose profile "test")
	$(COMPOSE) --profile test build api-tests
	$(COMPOSE) --profile test run --rm api-tests; status=$$?; $(COMPOSE) --profile test rm -sf postgres-test >/dev/null; exit $$status

e2e:           ## demo scenarios S1-S5 through the API of the running stack
	$(PYTHON) scripts/e2e_demo.py

openapi:       ## export docs/api/openapi.json from the FastAPI application
	cd services/api && uv run --python 3.12 --frozen python -m app.cli export-openapi ../../docs/api/openapi.json

web-install:   ## install frontend dependencies exactly from package-lock.json (Node 22+)
	cd web && npm ci --ignore-scripts

web-dev:       ## frontend dev server on http://localhost:5173 (proxies /api to http://localhost:8000)
	cd web && npm run dev

web-test:      ## frontend typecheck, unit/component tests and production build
	cd web && npm run typecheck && npm test && npm run build

web-types:     ## regenerate TypeScript API types from docs/api/openapi.json
	cd web && npm run gen:api

logs:          ## follow logs of all services
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps -a

reset:         ## DESTRUCTIVE: remove containers and the database volume, then start from scratch
	$(COMPOSE) down -v --remove-orphans
	$(COMPOSE) up --build -d --wait
