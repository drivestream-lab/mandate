# ADR-013: Repos (closes product OQ-03)

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-1 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

All public, in `drivestream-lab`. Repos are split wherever the trust boundary differs.

| Repo | Holds | Who can merge |
| --- | --- | --- |
| `mandate` | Python modular monolith; `mandate-context` is its own package and container inside it, kept apart by the import-boundary check | Mandate's App once Mandate governs itself; until then human review of Claude Code's work (REQ-120) |
| `mandate-control-tower` | TypeScript Paperclip plugin | As `mandate` |
| `mandate-verify` | The reusable verification workflow only; every governed repo references it by pinned tag | Named humans only, never a programme's agents |
| `mandate-meta` | Launchpad meta repo for Mandate's own programme; daily ledger checkpoint commits | As `mandate`, checkpoint written by its workflow |
| `mandate-sandbox-meta`, `mandate-sandbox-svc` | The sandbox programme: Launchpad meta repo and one toy service; a second toy repo is added during the sandbox fix stage to exercise adding a repo | Mandate's App, as for any governed programme |

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
