# Mandate: guide for Claude Code

@AGENTS.md

## Load the constitution first

`AGENTS.md` (managed by Launchpad, never edit its harness block) points at the shared rules. Claude Code does not load `.mdc` files on its own, so before any change read:

1. `.cursor/rules/code-guidelines-index.mdc`, then every rule it lists that applies to the change (at minimum `architecture.mdc`, `strong-typing.mdc`, `python-imports.mdc`, `dependency-injection.mdc`, `repository-pattern.mdc`, `pydantic-schemas.mdc`, `testing-verify-flows.mdc`, `database-migrations.mdc`, `spec-driven-development.mdc`).
2. `docs/specification/README.md`, then `docs/specification/product/mandate-core.md`.
3. The ADRs in `docs/specification/adr/` that touch the change.
4. Your task in `mandate-meta/Implementation-Plan-INIT-MANDATE-001.md` section 9 (clone `drivestream-lab/mandate-meta` beside this repo if it is not there).

Never edit `.cursor/rules/` or `prayog-skills/` here. Rule changes go upstream as pull requests.

## Build mode: Mandate is built by a Claude Code swarm

Until Mandate governs its own development (programme two), this repo is built by a Claude Code swarm (engineering-ready PRD PL-16, REQ-120): a stateless lead per round, builder subagents in their own worktrees, and challengers on a different model. That replaces the prayog wave workflow described in `AGENTS.md`:

| `AGENTS.md` (prayog v2) says | Here, instead |
| --- | --- |
| One Draft PR per wave, opened after `/loop-spec` | **One PR per task** from the WorkManifest, about 400 changed lines excluding generated code (ADR-021) |
| Human applies `wave-accepted`; merges at signoff nodes | A task PR merges into `develop` through `mandate-builder` when `mandate/build-verified` (posted only by `mandate-runner`) passes on its head. KD approves protected-path PRs, and signs each wave PR from `develop` into `main` (`wave-accepted`, attested Approve, ready) and merges it |
| Work tracked on the org Project board | No board (project board disabled). The WorkManifest, `docs/specification/as-built/` and the pinned build-log issue are the record |
| Forge skills do branch, commit, push, PR | Do them directly, as `mandate-builder` through `scripts/swarm/as_role.sh`, never as KD |

Roles live in `.claude/agents/`: `builder` (Sonnet 5.5), `challenger` and `second-challenger` (Opus 5.5, read-only, spec before diff), `verifier`, `integrator`. Wave B0 (the swarm itself) is the exception: KD merges every B0 PR.

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

## The lead: one round of the swarm

`make swarm` starts one headless lead per round (`scripts/swarm/run_swarm.sh`, prompt `scripts/swarm/lead_round.md`). The lead never writes code and never merges by judgement: it reads state, starts subagents, runs `scripts/swarm/merge_task.sh`, and records the round. An interactive session acting as lead follows the same rules.

### Identities

| Who | Acts as | How |
| --- | --- | --- |
| Lead, builders, integrator | `mandate-builder` (App 5860819) | `scripts/swarm/as_role.sh builder git ...` and `... builder gh ...` |
| Challengers | `mandate-challenger` (App 5860827) | `scripts/swarm/as_role.sh challenger gh ...` |
| Runner | `mandate-runner` (App 5860839) | Never used by the swarm. Its folder under `~/.mandate/secrets/build/` is never read or mounted |
| KD | `nikd10x` | Never used by the swarm: no commit, review, approval, merge or attestation as KD |

`GITHUB_TOKEN` on the lab machine is KD's own token. Never run plain `gh` or `git push`; `as_role.sh` removes it and mints the role's App token (`scripts/swarm/app_token.sh`, git credential helper `scripts/swarm/git-credential-mandate-app`). Each role reads only its own App's folder.

### Each round

1. **Rebuild state** from the repos and GitHub, never from memory: the WorkManifest (`mandate-meta` plan section 9), `docs/specification/as-built/requirements.md`, open and merged PRs on `mandate` and `mandate-control-tower` with their statuses and reviews, open `develop-red` issues, and the pinned build-log issue.
2. **Red develop first.** While a runner-opened `develop-red` issue is open, merge nothing. Start the `verifier` on it, then a builder on the fix (`Fixes #N` in the body); it needs KD's Approve, so that is a stop.
3. **Merge what is ready.** For each open task PR whose `mandate/build-verified` is green on the current head: if it touches a protected path (PL-16 list plus `.gitmodules`) and KD has not approved that head, stop and ask KD. Otherwise run `scripts/swarm/merge_task.sh <repo> <pr>`, which refuses unless base is `develop`, the runner's status is green on the head and develop is not red, and merges with the sha pinned. Never post a status.
4. **Reviews.** For each task PR head without a challenger review, start `challenger` on it. If the diff touches a trust-critical path (the runner config's `trust_critical_paths`: ledger, signoff check, evidence verification, merge control), also start `second-challenger`, independently. A red status on a reviewed head goes to the `verifier`; its findings, or a challenger's, go back to that task's `builder` as a fix round, and the new head is reviewed again. A task whose fixes fail three rounds is a stop.
5. **Keep PRs current.** PRs behind or conflicting with `develop` go to the `integrator`.
6. **Start ready tasks.** Every task of the current wave whose `depends_on` tasks are all merged into `develop`, and that has no open PR, gets a `builder` with branch `feature/INIT-MANDATE-001-w<n>-<task-slug>` from `origin/develop`, at most three builders running at once. Never stack a PR on unmerged work.
7. **Close the wave.** When every task of the wave has merged and develop is green, open the wave PR from `develop` into `main` as `mandate-builder`, with a brief: tasks merged, journeys run, findings, spend. That is a stop: KD signs and merges it, and the next wave starts only once `main` has moved.
8. **Record the round** as one comment on the build-log issue (below), then exit.

### Stop and wait for KD, only when

- a PR touches a protected path and needs KD's Approve on its head;
- a wave PR is open (KD adds `wave-accepted`, approves with `Initiative: INIT-MANDATE-001` and `Head: <sha>`, marks it ready, merges);
- the spec is unclear or contradicts itself, or a decision is not covered by the PRDs: post the question with options and a recommendation, never choose silently;
- a task failed three rounds;
- something needs KD on GitHub, Paperclip or the lab machine (rulesets, App settings, secrets, the lab env file);
- spend reaches 80% of the wave's cap ($1,000 per wave): sum the round spends recorded in the build log since the wave started.

To stop: write the build-log entry with a `Waiting on KD` section giving the exact command or click needed, mentioning KD, and exit. Work that does not depend on the answer carries on in later rounds; the next round sees KD's action on GitHub and continues from there.

### The build log

One pinned issue on `drivestream-lab/mandate`, titled `Build log: INIT-MANDATE-001`, labelled `build-log`, opened and written by `mandate-builder`. If it does not exist, the lead opens and pins it. Each round appends one comment:

```
Round <SWARM_ROUND_ID> (wave W<n>)
Started: <task ids and PRs>
Merged: <PRs and merge shas>
Failed: <PRs, rule or command, round count>
Waiting on KD: <none, or each item with the exact command or click>
Spend: last completed round $<x>; wave W<n> so far $<y> of $1,000
```

No secrets, no em dashes. Spend per completed round is in `~/.mandate/swarm/spend.tsv` (round id, USD, exit code), written by `make swarm` after each round exits. Wave spend is the sum of its rows from the wave's first round (named in the build log) onward.
