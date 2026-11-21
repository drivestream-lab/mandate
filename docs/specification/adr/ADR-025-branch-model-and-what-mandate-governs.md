# ADR-025: Branch model and what Mandate governs

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-13 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Launchpad's enforced branching policy (GitFlow: `develop` integration line, `main` release line) is adopted unchanged. On governed repos every merge into either line is a gate, enforced by one required check, `mandate/gate-decision`:

| Merge | Gate | Signoff label | Merged by at L0 | Default holder at L0 |
| --- | --- | --- | --- | --- |
| PRD PR into meta `develop` | `prd-impact-acceptance` (intent) | `impact-map-lgtm` | PM | Principal engineer |
| Spec PR into app `develop` | `coding-readiness` (design) | `spec-lgtm` | Engineering | Principal engineer |
| Wave PR into app `develop` | `wave-acceptance` then `wave-signoff` (verification) | `wave-accepted` | Engineering | Release holder |
| Closure purge PRs | `initiative-closure-signoff-app` and `-meta` (housekeeping) | as the workflow defines | Engineering, product | Engineering gate |
| `develop` into `main` | Production release (verification); `mandate-verify` on the head being promoted | as the workflow defines | Launchpad's `release-managers` | `release-managers`; held for a human by default policy, which the owner may relax |

At L2 and L3 the deciding role signs and Mandate's App applies the label, attested Approve and ready state, and merges. `technical-review-approval` and the clarification checkpoints are recorded decisions and questions, not gates.

While Mandate itself is built (REQ-120), the same lines apply without Mandate: feature PRs go to `develop` under human review, and a human promotes `develop` to `main`.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
