.PHONY: setup check check-ci format format-check lint lint-check types layers test journeys run deploy deploy-down verify integration

setup:
	@bash scripts/setup_dev.sh

check: format lint types layers

check-ci: format-check lint-check types layers

format:
	.venv/bin/black --line-length 100 src/ tests/

format-check:
	.venv/bin/black --check --line-length 100 src/ tests/

lint:
	.venv/bin/ruff check --fix src/ tests/

lint-check:
	.venv/bin/ruff check src/ tests/

types:
	.venv/bin/pyright

layers:
	.venv/bin/lint-imports

test:
	.venv/bin/pytest tests/unit/ tests/properties/ -v --require-req-coverage

# make journeys: the end-to-end journeys against the local ephemeral stack. Paths and pytest
# options go in ARGS: make journeys ARGS="tests/journeys/foo.py -x". With none, every journey
# under tests/journeys runs. (A later task builds the stack they run on.)
journeys:
	.venv/bin/pytest $(if $(ARGS),$(ARGS),tests/journeys) -v

run:
	.venv/bin/python -m src.main

# make deploy: build this branch in Docker and run it with its .env (on its own Postgres
# and Redis). make verify: every journey against what deploy started, or against
# MANDATE_SERVICE_URL when it is set (after a merge, the runner points it at the lab).
# DEPLOY_PROJECT and MANDATE_DEPLOY_PORT let several branches run side by side (the
# swarm's verifier deploys each PR in its own worktree).
DEPLOY_PROJECT ?= mandate-deploy
DEPLOY_COMPOSE := docker compose -p $(DEPLOY_PROJECT) -f docker/docker-compose.deploy.yml
MANDATE_DEPLOY_PORT ?= 8000
# Inside mandate-runner's job container (it sets MANDATE_RUNNER_HEAD_SHA) the stack is
# reached over its own network, by service name.
ifdef MANDATE_RUNNER_HEAD_SHA
MANDATE_SERVICE_URL ?= http://mandate:8000
else
MANDATE_SERVICE_URL ?= http://localhost:$(MANDATE_DEPLOY_PORT)
endif
export MANDATE_SERVICE_URL MANDATE_DEPLOY_PORT DEPLOY_PROJECT

deploy:
	$(DEPLOY_COMPOSE) up -d --build --wait --wait-timeout 300
ifdef MANDATE_RUNNER_HEAD_SHA
	@docker inspect -f '{{json .NetworkSettings.Networks}}' "$$(hostname)" | grep -q '"$(DEPLOY_PROJECT)_default"' \
		|| docker network connect "$(DEPLOY_PROJECT)_default" "$$(hostname)"
endif
	@echo "mandate deployed at $(MANDATE_SERVICE_URL)"

deploy-down:
	$(DEPLOY_COMPOSE) down -v

verify:
	python3 tests/verify/verify_health.py
ifeq ($(origin MANDATE_SERVICE_URL),environment)
	@echo "verify: integration tests not run: MANDATE_SERVICE_URL points at a service this checkout did not deploy (the lab has no superuser to make throwaway databases)"
else
	@$(MAKE) --no-print-directory integration
endif

# make integration: the real-Postgres tests (tests/integration) against make deploy's own
# Postgres, with its throwaway credentials read from the running container (KD, 27 Nov 2026:
# make verify runs them, so the runner gates them on every PR).
integration:
	@set -e; \
	if [ -n "$$MANDATE_RUNNER_HEAD_SHA" ]; then host=postgres; port=5432; \
	else hp=$$($(DEPLOY_COMPOSE) port postgres 5432); host=$${hp%:*}; port=$${hp##*:}; fi; \
	test -n "$$host" && test -n "$$port" || { echo "integration: no make deploy stack ($(DEPLOY_PROJECT)); run make deploy first" >&2; exit 1; }; \
	envs=$$($(DEPLOY_COMPOSE) exec -T postgres printenv); \
	pw() { printf '%s\n' "$$envs" | sed -n "s/^$$1=//p"; }; \
	MANDATE_DB_HOST=$$host MANDATE_DB_PORT=$$port MANDATE_DB_NAME=ds_mandate_db \
	MANDATE_DB_ADMIN_USER=postgres MANDATE_DB_ADMIN_PASSWORD="$$(pw POSTGRES_PASSWORD)" \
	MANDATE_DB_OWNER_PASSWORD="$$(pw MANDATE_DB_OWNER_PASSWORD)" MANDATE_DB_APP_PASSWORD="$$(pw MANDATE_DB_APP_PASSWORD)" \
	.venv/bin/pytest tests/integration -v

