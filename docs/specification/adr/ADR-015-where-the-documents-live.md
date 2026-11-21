# ADR-015: Where the documents live

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-3 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Once the layout questions close, these documents are exported to the repos, which become the source of truth; the Claude docs are then marked as archived snapshots. The export is the first commit to `mandate-meta`, before W1. It follows Launchpad's meta conventions and the rules' truth hierarchy (`.cursor/rules/` how, `docs/specification/product/` what, `adr/` why, `as-built/` what is live).

| Location | Content |
| --- | --- |
| `mandate-meta/planning/` | Product vision |
| `mandate-meta/prd/INIT-MANDATE-001.md` | Product PRD |
| `mandate-meta/prd/INIT-MANDATE-001-engineering.md` | This engineering-ready PRD |
| `mandate-meta/Implementation-Plan-INIT-MANDATE-001.md` | Wave plan; section 9 is the WorkManifest under the pinned prayog contract |
| `<repo>/docs/specification/product/` | That repo's slice: its requirements, contracts and data model |
| `<repo>/docs/specification/adr/` | AD-1 to AD-12 and PL-1 onward as ADR-001 and up; immutable, superseded only by a new ADR |
| `<repo>/docs/specification/as-built/` | One row per requirement (implemented, unit-tested, live-verified), starting empty |

Every PR updates spec, tests and as-built together (same-PR discipline) and names the initiative, issue, spec paths and verify command.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
