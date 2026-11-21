# ADR-027: Launchpad credentials (product OQ-13)

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-15 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Launchpad runs under its own GitHub App, the Launchpad App, executed by a Mandate worker and never by an agent. Its key is held like Mandate's other secrets (PL-7) and never mounted into an agent workspace. The platform engineer agent proposes the run as a reviewed meta repo change (repo, stack, YAML); once the design gate is decided (REQ-99), the worker runs `init-client` and `apply-harness` on the merged config only. Mandate then reads the branch rules back to confirm they are in force; the sweep detects any branch-protection change not made by a decided Launchpad run, reverts it and escalates.

Grounding note: Launchpad 0.5.39 authenticates with a fine-grained factory PAT (`GITHUB_TOKEN`), not a GitHub App. Until Launchpad supports App authentication, the Mandate worker holds that factory PAT under the same rules (outside every repo, never mounted into an agent workspace, separate per environment). Moving Launchpad to App authentication is an upstream change to Launchpad, needed before Conduit's fix stage, when an agent first triggers a Launchpad run.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
