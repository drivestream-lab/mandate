# Mandate: guide for Claude Code

@AGENTS.md

## Load the constitution first

`AGENTS.md` (managed by Launchpad, never edit its harness block) points at the shared rules. Claude Code does not load `.mdc` files on its own, so before any change read:

1. `.cursor/rules/code-guidelines-index.mdc`, then every rule it lists that applies to the change (at minimum `architecture.mdc`, `strong-typing.mdc`, `python-imports.mdc`, `dependency-injection.mdc`, `repository-pattern.mdc`, `pydantic-schemas.mdc`, `testing-verify-flows.mdc`, `database-migrations.mdc`, `spec-driven-development.mdc`).
2. `docs/specification/README.md`, then `docs/specification/product/mandate-core.md`.
3. The ADRs in `docs/specification/adr/` that touch the change.
4. Your task in `mandate-meta/Implementation-Plan-INIT-MANDATE-001.md` section 9 (clone `drivestream-lab/mandate-meta` beside this repo if it is not there).

Never edit `.cursor/rules/` or `prayog-skills/` here. Rule changes go upstream as pull requests.

## Build mode: Mandate is built under human review

Until Mandate governs its own development (programme two), this repo is built by Claude Code under KD's review (REQ-120). That replaces the prayog wave workflow described in `AGENTS.md`:

| `AGENTS.md` (prayog v2) says | Here, instead |
| --- | --- |
| One Draft PR per wave, opened after `/loop-spec` | **One PR per task** from the WorkManifest, about 400 changed lines excluding generated code (ADR-021) |
| Human applies `wave-accepted`; merges at signoff nodes | KD reviews and merges each PR into `develop`. No `wave-accepted` label |
| Work tracked on the org Project board | No board (project board disabled). The WorkManifest and `docs/specification/as-built/` are the record |
| Forge skills do branch, commit, push, PR | Do them directly, but only when KD asks; never push without an explicit go-ahead |

The prayog content skills (`/spec-draft`, `/loop-spec` and the like) are not used for this build.

## Every task

- **Branch:** Launchpad's policy, `feature/INIT-MANDATE-001-w<n>-<task-slug>` from `develop` (ADR-025). Use `fix/` or `chore/` only as Launchpad defines them.
- **Scope:** exactly one WorkManifest task. If the task needs more, stop and say so; do not widen it.
- **Same PR:** code, tests, the spec if behaviour changes, and the task's rows in `docs/specification/as-built/requirements.md`.
- **Checks, run locally and attached to the PR** (ADR-018; there is no CI on this repo):
  - `make check` (Black, Ruff, pyright strict, import-linter)
  - `make test` (unit, properties, simulation)
  - `make journeys` for every end-to-end flow the task touches (live, against the local ephemeral stack)
- **PR body:** initiative `INIT-MANDATE-001`, task id, spec paths, verify command, and the check output.

## Non-negotiables

- **No fakes** (ADR-017). Test against the real Paperclip (ephemeral pinned instance) and real GitHub sandbox repos. Where a condition cannot be produced live, unit-test the pure function that handles it.
- **Purpose names in code** (ADR-023). No REQ, J, CTR, AD or PL ids in module, file, function, test or fixture names. Ids appear in code only as `@pytest.mark.req("REQ-63")` traceability markers.
- **Typing** per the rules: pyright strict, Pydantic v2 at every boundary, `StrEnum` with a `Type` suffix, no `Any`, no `# type: ignore`, no `TYPE_CHECKING` imports.
- **Layers** per ADR-014: pure rules in `engine/` import no IO; only `infra_services/` talk to Paperclip, GitHub, Temporal or LiteLLM; extension points are `Protocol`s with a `StrEnum` registry bound in `di/modules/`.
- **Database** per ADR-020: a schema per capability; `mandate_app` may only insert and select on `ledger.entries`; migrations are created with `scripts/create_postgres_migration.sh` and applied only by a human.
- **Secrets** never in the repo, logs, ledger or test output (ADR-019). Settings read file paths under `~/.mandate/secrets/<env>/`.
- **Mandate never judges** (ER-04). Its code applies typed rules, schema checks and comparisons; judgement is a role agent's call or a human's decision.
- **Unknown means stop** (ER-09). An unrecognised Paperclip release, contract block version or signature stops the work and escalates; never fall back to a default.
- **Avoid em dashes** in docs, comments and PR text.

## When unsure

Ask KD in the PR or the chat. Do not guess intent from code that is not there yet.
