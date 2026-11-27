# ADR-028: Temporal workflows live in `engine/workflows`

- Status: accepted
- Date: 27 Nov 2026
- Source: KD decision 27 Nov 2026 and PL-2 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`
- Supersedes in part: ADR-014 (the `workflows/` location and the "Upstream change" note)

## Decision

- Temporal workflow definitions live in `src/engine/workflows/`. Workflow code must be deterministic, which is the rules' definition of `engine/` ("deterministic domain logic without HTTP/DB").
- Only `engine.workflows` may import `temporalio.workflow`. import-linter enforces it.
- Activities, which do the I/O, stay in `business_services/`. Workflows call them by name through typed stubs: a `StrEnum` of activity names with Pydantic input and output models in `models/`. A unit test checks that every name is registered in `worker_main.py`.
- `python-services-rules` is unchanged: there is no upstream pull request, and `.cursor/rules/` is not edited.

## Consequences

- ADR-014's package table entry `workflows/` and its "Upstream change" paragraph no longer apply; the rest of ADR-014 stands.
- `engine` imports no IO layer, so workflows import neither `business_services` nor `infra_services`.
- Adding an activity is an enum value, its models and its registration; the registry test fails until all three exist.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
