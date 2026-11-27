# Multi-stage build for mandate.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential curl && rm -rf /var/lib/apt/lists/*
RUN pip install poetry

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false && \
    poetry install --only=main --no-root --no-interaction --no-ansi

FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app app

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ ./src/
COPY postgres_migrations/ ./postgres_migrations/
COPY scripts/ ./scripts/
COPY docker/mandate/entrypoint.sh ./entrypoint.sh
# Code is root-owned and not writable by the app user: the entrypoint runs scripts and
# migrations as root, so the service must not be able to rewrite them.
RUN chmod +x entrypoint.sh && chmod +x scripts/*.sh && chmod -R go-w src postgres_migrations scripts entrypoint.sh
RUN mkdir -p logs && chown app:app logs

USER app
EXPOSE 8000

HEALTHCHECK --interval=300s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
