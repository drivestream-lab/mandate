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

It runs the image with `~/.mandate/lab/mandate.env` (kept outside the repos, mode 600). Without that file the deploy fails and develop goes red. A missing key of either set stops the start, naming the key; neither set stands in for the other. The file needs:

| Key | Value |
| --- | --- |
| `POSTGRES_HOST`, `POSTGRES_PORT` | `lab-postgres`, `5432` |
| `POSTGRES_DB` | `mandate` (the runner refuses any other database) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD` | the app set: `mandate_app` and its password from dev-infra-lab's `.env` (`MANDATE_DB_APP_PASSWORD`). The service connects with these and nothing else |
| `POSTGRES_MIGRATION_USER`, `POSTGRES_MIGRATION_PASSWORD` | the owner set: `mandate_owner` and its password (`MANDATE_DB_OWNER_PASSWORD`). The entrypoint runs the migrations with these, then starts the service without them; `mandate_owner` must own the `mandate` database |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` | `lab-redis`, `6379`, `0` |
| `APP_ENVIRONMENT`, `APP_PORT` | `development`, `8000` |

Leave `JWT_PUBLIC_KEY_PATH` unset: the image holds no key file, so a path makes every request answer 500.
