#!/bin/bash
set -e

echo "[INFO] Starting mandate with database migrations"

# Two credential sets, never mixed. The app's (POSTGRES_USER, POSTGRES_PASSWORD_FILE) is the
# service's connection; the owner's (POSTGRES_MIGRATION_USER, POSTGRES_MIGRATION_PASSWORD_FILE)
# runs the migrations only. Each password is a file read by path; no password travels as an
# environment value, and neither set stands in for the other. A missing key or an unreadable
# file stops the start and names it.
for key in POSTGRES_USER POSTGRES_PASSWORD_FILE POSTGRES_MIGRATION_USER POSTGRES_MIGRATION_PASSWORD_FILE; do
    if [ -z "${!key:-}" ]; then
        echo "[ERROR] ${key} is not set; refusing to start (no fallback to the other credential set)"
        exit 1
    fi
done
for key in POSTGRES_PASSWORD POSTGRES_MIGRATION_PASSWORD; do
    if [ -n "${!key+x}" ]; then
        echo "[ERROR] ${key} is set; passwords are read from ${key}_FILE, never from the environment"
        exit 1
    fi
done
for key in POSTGRES_PASSWORD_FILE POSTGRES_MIGRATION_PASSWORD_FILE; do
    if [ ! -r "${!key}" ]; then
        echo "[ERROR] ${key}: ${!key} is missing or unreadable; refusing to start"
        exit 1
    fi
done

# Started as root, the entrypoint reads both files, runs the migrations, then drops to the
# app user for the service, so the owner's file can be mode 600 and unreadable to the service.
SERVICE_USER=app
DROP=()
if [ "$(id -u)" = "0" ]; then
    DROP=(setpriv --reuid="${SERVICE_USER}" --regid="${SERVICE_USER}" --init-groups)
    if "${DROP[@]}" test -r "${POSTGRES_MIGRATION_PASSWORD_FILE}"; then
        echo "[ERROR] POSTGRES_MIGRATION_PASSWORD_FILE is readable by the service user; make it owner-only (mode 600, root)"
        exit 1
    fi
fi

wait_for_db() {
    python -c "
import os, sys, time
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

def check_postgres():
    try:
        db_host = os.getenv('POSTGRES_HOST', 'localhost')
        db_port = os.getenv('POSTGRES_PORT', '5432')
        db_name = os.getenv('POSTGRES_DB', 'ds_mandate_db')
        db_user = os.environ['POSTGRES_USER']
        db_pass = open(os.environ['POSTGRES_PASSWORD_FILE']).read().strip()
        db_pass_encoded = quote_plus(db_pass)
        connection_string = f'postgresql+psycopg2://{db_user}:{db_pass_encoded}@{db_host}:{db_port}/{db_name}'
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        print('[OK] PostgreSQL is ready')
        return True
    except Exception as e:
        print(f'[ERROR] PostgreSQL not ready: {e}')
        return False

for _ in range(60):
    if check_postgres():
        sys.exit(0)
    time.sleep(1)
print('[ERROR] Database not ready after 60 seconds')
sys.exit(1)
"
}

wait_for_db
PYTHONDONTWRITEBYTECODE=1 ./scripts/run_postgres_migration.sh
# The service starts as the app user, without the owner's user or file path in its environment.
exec "${DROP[@]}" env -u POSTGRES_MIGRATION_USER -u POSTGRES_MIGRATION_PASSWORD_FILE HOME=/app python -m src.main
