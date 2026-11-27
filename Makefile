.PHONY: setup check check-ci format format-check lint lint-check types layers test run deploy deploy-down verify swarm swarm-once swarm-stop

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

run:
	.venv/bin/python -m src.main

# make deploy: build this branch in Docker and run it with its .env (on its own Postgres
# and Redis). make verify: every journey against what deploy started, or against
# MANDATE_SERVICE_URL when it is set (after a merge, the runner points it at the lab).
DEPLOY_COMPOSE := docker compose -f docker/docker-compose.deploy.yml
MANDATE_DEPLOY_PORT ?= 8000
# Inside mandate-runner's job container (it sets MANDATE_RUNNER_HEAD_SHA) the stack is
# reached over its own network, by service name.
ifdef MANDATE_RUNNER_HEAD_SHA
MANDATE_SERVICE_URL ?= http://mandate:8000
else
MANDATE_SERVICE_URL ?= http://localhost:$(MANDATE_DEPLOY_PORT)
endif
export MANDATE_SERVICE_URL MANDATE_DEPLOY_PORT

deploy:
	$(DEPLOY_COMPOSE) up -d --build --wait --wait-timeout 300
ifdef MANDATE_RUNNER_HEAD_SHA
	@docker network connect mandate-deploy_default "$$(hostname)" 2>/dev/null || true
endif
	@echo "mandate deployed at $(MANDATE_SERVICE_URL)"

deploy-down:
	$(DEPLOY_COMPOSE) down -v

verify:
	python3 tests/verify/verify_health.py

# The build swarm (PL-16 BP-7): one headless Claude Code lead per round, until stopped.
# Stateless: a restart resumes from repo state. See CLAUDE.md "The lead".
SWARM_DIR ?= $(HOME)/.mandate/swarm

swarm:
	@bash scripts/swarm/run_swarm.sh

swarm-once:
	@SWARM_ONCE=1 bash scripts/swarm/run_swarm.sh

swarm-stop:
	@mkdir -p "$(SWARM_DIR)" && touch "$(SWARM_DIR)/STOP"
	@echo "the swarm stops after its current round"
