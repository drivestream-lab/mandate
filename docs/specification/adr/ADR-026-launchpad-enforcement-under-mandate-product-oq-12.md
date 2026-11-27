# ADR-026: Launchpad enforcement under Mandate (product OQ-12)

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-14 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

| Launchpad mechanism | On governed repos | On Mandate's own repos while it is built |
| --- | --- | --- |
| Branch protection | One required check, `mandate/gate-decision`, on `develop` and `main` | Launchpad default; the human review is the gate (REQ-120) |
| `require_pr_reviews` | 0; the attested Approve is part of the signoff Mandate checks, not a GitHub count | 1 |
| Merge | The workflow's merger at L0; Mandate's App at L2 and L3; GitHub refuses either without the check | Human |
| `*-lgtm`, `wave-accepted` labels | Part of the signoff; Mandate reads them at L0 and applies them at L2 and L3; `-revised` and `-stale` as the workflow defines | As Launchpad |
| Review roles | Mapped to gate holders by rung | Human reviewer |
| Seeded `ci.yml` | Replaced by a small caller of `mandate-verify` | None (PL-6) |
| `policy-branch-name`, `policy-merge-source` | Kept | Kept |

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
