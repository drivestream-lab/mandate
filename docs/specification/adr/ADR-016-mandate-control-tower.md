# ADR-016: `mandate-control-tower`

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-4 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Scaffolded with Paperclip's `create-paperclip-plugin` against the SDK at the pinned baseline commit: typed manifest, worker entrypoint, UI on the SDK's hooks and host components, tests on `@paperclipai/plugin-sdk/testing`. TypeScript `strict`. The Mandate API client is generated from Mandate's OpenAPI schema; CI regenerates it and fails on any diff, so a Pydantic change either flows through or breaks the build. The plugin holds no logic and no state: UI and event forwarding only, and no second place to decide (REQ-86). It is enrolled under a new Launchpad stack, `paperclip-plugin`, whose constitution is a new short rules repo, `paperclip-plugin-rules` (strict TypeScript, generated client only, SDK hooks and host components only, no business logic).

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
