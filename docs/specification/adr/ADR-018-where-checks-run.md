# ADR-018: Where checks run

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-6 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Building Mandate runs every check locally; GitHub Actions runs only the two trust anchors.

| Where | What | Why |
| --- | --- | --- |
| Local, Mandate's own repos | `make check` (Black, Ruff, pyright strict, import-linter); `make test` (unit, properties, simulation); `make journeys` (live, against an ephemeral local Compose stack of pinned Paperclip, Postgres and Temporal, plus real GitHub sandbox repos). pre-commit on commit, pre-push on push; Claude Code attaches the run output to each PR and the human review is the gate (REQ-120) | Ordinary hygiene; fastest loop; no Actions CI to maintain |
| GitHub Actions | `mandate-verify` on governed repos (sandbox, then Conduit) and the checkpoint workflow in `mandate-meta` | The run's own identity signs the evidence and the checkpoint, which no agent controls (AD-5, AD-7, REQ-108); free for public repos |

When Mandate's own development joins as programme two, its repos switch to `mandate-verify`, because agents then merge its code.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
