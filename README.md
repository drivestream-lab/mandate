# mandate
Mandate core (modular monolith) and the mandate-context gateway

## Run, deploy, verify

```bash
make setup     # .venv and packages
make check     # Black, Ruff, pyright, import-linter
make test      # unit tests
make deploy    # build this branch in Docker and run it on its own Postgres and Redis
make verify    # every journey against what deploy started (or MANDATE_SERVICE_URL)
make deploy-down
```

## The lab deploy (after every merge into develop)

`mandate-runner` (in `mandate-verify`) deploys each merge into `develop` to the lab as `lab-mandate` on `lab_local`, then runs `make verify` against `http://lab-mandate:8000`. A red run opens a `develop-red` issue and freezes task merges until a later develop run is green.

It runs the image with `~/.mandate/lab/mandate.env` (kept outside the repos, mode 600) and the two database password files. The env file keeps only non-secret settings; no password is an environment value. Without the env file or either password file the deploy fails and develop goes red. A missing key or password file stops the start, naming it; neither set stands in for the other.

The password files live in `~/.mandate/lab/secrets/` (mode 600): `app-password` (the app role's password, `MANDATE_DB_APP_PASSWORD` in dev-infra-lab's `.env`) and `owner-password` (the owner role's, `MANDATE_DB_OWNER_PASSWORD`). Each holds only the password. The runner's deployer mounts them read-only into the container at `/run/mandate/app-password` and `/run/mandate/owner-password`, and starts the container as root, which the entrypoint requires (it refuses to start otherwise): it reads the owner file for the migration and then drops to the app user, which cannot read `owner-password` (the entrypoint refuses to start if it can). The code in the image is root-owned and read-only to the app user. The env file needs:

| Key | Value |
| --- | --- |
| `POSTGRES_HOST`, `POSTGRES_PORT` | `lab-postgres`, `5432` |
| `POSTGRES_DB` | `mandate` (the runner refuses any other database) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD_FILE` | the app set: `mandate_app` and `/run/mandate/app-password`. The service connects with these and nothing else |
| `POSTGRES_MIGRATION_USER`, `POSTGRES_MIGRATION_PASSWORD_FILE` | the owner set: `mandate_owner` and `/run/mandate/owner-password`. The entrypoint runs the migrations with these, then starts the service without them; `mandate_owner` must own the `mandate` database |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | `lab-redis`, `6379`, `0` |
| `APP_ENVIRONMENT`, `APP_PORT` | `development`, `8000` |

`POSTGRES_PASSWORD`, `POSTGRES_MIGRATION_PASSWORD` and `PGPASSWORD` are refused if set, even empty. `make deploy` provides throwaway files from `docker/deploy-secrets/`.

Leave `JWT_PUBLIC_KEY_PATH` unset: the image holds no key file, so a path makes every request answer 500.
