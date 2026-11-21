# ADR-024: Sandbox service

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-12 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

`mandate-sandbox-svc` is a `python-backend` service scaffolded through Launchpad from `python-fastapi-foundation`, under `python-services-rules`, with one in-memory resource (`/items`) and no database. It goes through the same stack, constitution, harness and scaffold path as Conduit's backend, so onboarding is tested for real, and it is small enough that any failure on the sandbox is Mandate's. The second toy repo added during the sandbox fix stage uses the same template.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
