# ADR-020: Database layout and ledger protection

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-8 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

One database, `mandate`, with one Postgres schema per capability (`gates`, `ledger`, `autonomy`, `policy`, `runner` and the rest, matching the PL-2 sub-packages); each repository touches only its own schema. Roles split by duty: `mandate_owner` owns every object and is used only by the human-run migration script; `mandate_app` is the runtime role, with read and write on its tables but only `INSERT` and `SELECT` on `ledger.entries`. A trigger rejects `UPDATE` and `DELETE` on the ledger, even for the owner, except in a migration explicitly marked for it. One Alembic history, created and applied as the rules require (agent runs `create_postgres_migration.sh`, a human runs `run_postgres_migration.sh`). A decision, its ledger entry and its outbox row commit in one transaction (AD-4). The database prevents tampering; the hash chain and checkpoint (AD-5) detect it.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
