#!/bin/bash
set -e

echo "[INFO] Starting mandate with database migrations"

# Two credential sets, never mixed: the app's (POSTGRES_USER, POSTGRES_PASSWORD) is the
# service's connection; the owner's (POSTGRES_MIGRATION_USER, POSTGRES_MIGRATION_PASSWORD)
# runs the migrations only. A missing key stops the start; neither set stands in for the other.
for key in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_MIGRATION_USER POSTGRES_MIGRATION_PASSWORD; do
    if [ -z "${!key:-}" ]; then
        echo "[ERROR] ${key} is not set; refusing to start (no fallback to the other credential set)"
        exit 1
    fi
done

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
        db_pass = os.environ['POSTGRES_PASSWORD']
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
./scripts/run_postgres_migration.sh
# The service starts without the owner's credentials in its environment.
exec env -u POSTGRES_MIGRATION_USER -u POSTGRES_MIGRATION_PASSWORD python -m src.main
