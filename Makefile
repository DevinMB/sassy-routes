COMPOSE ?= docker compose

# `pipeline` and `import-graph` must be here: ./pipeline is a real directory, so
# without .PHONY make considers the target up to date and silently does nothing.
.PHONY: help init seed up tunnel beta promote retune down restart logs ps test clean-graph pipeline import-graph

help: ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

init: ## create .env from template if missing (random couchdb password)
	@if [ ! -f .env ]; then \
		sed "s/^COUCHDB_PASSWORD=.*/COUCHDB_PASSWORD=$$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')/" .env.example > .env; \
		echo "created .env (edit as needed)"; \
	else echo ".env already exists"; fi

seed: init ## download the Michigan OSM extract (idempotent, resumable)
	./infra/seed.sh

up: ## build and start the whole stack (local; no tunnel)
	$(COMPOSE) up -d --build

tunnel: ## build and start the whole stack incl. the Cloudflare tunnel
	@token=$$(grep -E '^TUNNEL_TOKEN=.+' .env | cut -d= -f2-); \
	if [ -z "$$token" ]; then \
		echo "TUNNEL_TOKEN is empty in .env — paste the Cloudflare tunnel token first."; exit 1; \
	fi
	COMPOSE_PROFILES=tunnel $(COMPOSE) up -d --build

beta: ## rebuild just the staging UI at /beta (production untouched)
	$(COMPOSE) up -d --build frontend-beta

reload-proxy: ## apply Caddyfile edits (it's bind-mounted, so compose won't notice)
	$(COMPOSE) restart caddy

promote: ## ship what's on /beta to the production UI
	$(COMPOSE) up -d --build frontend

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

retune: ## apply scoring.yaml edits, doing only the work they need (FORCE=1 for all of it)
	@./infra/retune.sh

pipeline: ## score all segments into CouchDB + fun CSV (full rebuild, ~5-10 min)
	$(COMPOSE) run --build --rm pipeline

import-graph: ## rebuild the routing graph with fun scores baked in (site stays up; ~1 min swap at the end)
	@echo "building into data/graph-staging — the live graph keeps serving..."
	docker run --rm -v $(PWD)/data:/data alpine rm -rf /data/graph-staging
	$(COMPOSE) run --build --rm gh-import
	@echo "graph built; swapping in (this is the only downtime)"
	$(COMPOSE) stop graphhopper
	docker run --rm -v $(PWD)/data:/data alpine \
		sh -c 'rm -rf /data/graph-cache && mv /data/graph-staging /data/graph-cache'
	$(COMPOSE) start graphhopper
	@echo "done — graphhopper is reloading the new graph"

clean-graph: ## delete the graphhopper graph cache (forces reimport on next up)
	$(COMPOSE) stop graphhopper
	docker run --rm -v $(PWD)/data:/data alpine rm -rf /data/graph-cache
