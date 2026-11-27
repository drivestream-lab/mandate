.PHONY: setup check check-ci format format-check lint lint-check types layers test run swarm swarm-once swarm-stop

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
