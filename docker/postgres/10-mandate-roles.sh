#!/bin/bash
# Deploy stack only: create the two roles the lab already has (dev-infra-lab provisions them
# there), so the migration meets the same roles in `make deploy`, in the runner's sandbox and
# in the lab. Runs once, on the first start of an empty data directory, as the superuser.
# The passwords come from the container environment (throwaway values in
# docker-compose.deploy.yml); none are written here.
set -euo pipefail

: "${MANDATE_DB_OWNER_PASSWORD:?set in the compose file}"
: "${MANDATE_DB_APP_PASSWORD:?set in the compose file}"

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v owner_password="$MANDATE_DB_OWNER_PASSWORD" \
  -v app_password="$MANDATE_DB_APP_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE mandate_owner LOGIN PASSWORD %L', :'owner_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mandate_owner') \gexec
SELECT format('CREATE ROLE mandate_app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mandate_app') \gexec
SQL
