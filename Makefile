COMPOSE ?= docker compose

.PHONY: help init seed up down restart logs ps test clean-graph

help: ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

init: ## create .env from template if missing (random couchdb password)
	@if [ ! -f .env ]; then \
		sed "s/^COUCHDB_PASSWORD=.*/COUCHDB_PASSWORD=$$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')/" .env.example > .env; \
		echo "created .env (edit as needed)"; \
	else echo ".env already exists"; fi

seed: init ## download the Michigan OSM extract (idempotent, resumable)
	./infra/seed.sh

up: ## build and start the whole stack
	$(COMPOSE) up -d --build

down: ## stop the stack
	$(COMPOSE) down

restart: down up ## restart the stack

logs: ## tail logs
	$(COMPOSE) logs -f --tail=100

ps: ## show service status
	$(COMPOSE) ps

test: ## run backend tests (uses uv if available, else python venv)
	cd backend && \
	if command -v uv >/dev/null 2>&1; then \
		{ [ -d .venv ] || uv venv -q .venv; } && \
		uv pip install -q -p .venv/bin/python -r requirements.txt -r requirements-dev.txt; \
	else \
		{ [ -d .venv ] || python3 -m venv .venv; } && \
		.venv/bin/pip install -q -r requirements.txt -r requirements-dev.txt; \
	fi && \
	.venv/bin/python -m pytest -q

pipeline: ## score all segments into CouchDB (full rebuild, ~10-30 min)
	$(COMPOSE) run --build --rm pipeline

clean-graph: ## delete the graphhopper graph cache (forces reimport on next up)
	$(COMPOSE) stop graphhopper
	docker run --rm -v $(PWD)/data:/data alpine rm -rf /data/graph-cache
