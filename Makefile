.PHONY: setup check check-ci format format-check lint lint-check types layers test journeys run deploy deploy-down verify

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
	.venv/bin/pytest tests/unit/ -v

# make journeys: the end-to-end journeys against the local ephemeral stack. Extra paths and
# pytest options pass through after a double dash: make journeys -- tests/journeys/foo.py -x
# With none, every journey under tests/journeys runs. (W0-06 builds the stack they run on.)
ifneq ($(filter journeys,$(MAKECMDGOALS)),)
JOURNEY_ARGS := $(filter-out journeys,$(MAKECMDGOALS))
$(JOURNEY_ARGS): ; @:
endif

journeys:
	.venv/bin/pytest $(if $(JOURNEY_ARGS),$(JOURNEY_ARGS),tests/journeys) -v

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

