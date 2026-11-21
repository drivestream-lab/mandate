# ADR-014: Inside `mandate`

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-2 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

`mandate` is a standard `python-backend` repo under `python-services-rules` (v0.5.12 read on 19 Nov 2026), mounted as a submodule at `.cursor/rules/` and never edited in place. The rules' layered `src/` layout, naming, DI, typing and tooling apply unchanged; the section 7 capabilities become sub-packages inside each layer.

```
src/
  main.py, app.py            entry and composition root (API process)
  worker_main.py             Temporal workers and the sweep
  context_main.py            mandate-context gateway (own container)
  configs/  logging/  di/  exceptions/  utils/
  api/                       plugin backend, webhooks (built, disabled), health
  business_services/<capability>/   *_service.py per use case
  engine/<capability>/       pure rules, no IO: promotion and demotion, policy evaluation, ledger hash chain, wave planning
  workflows/                 Temporal workflow definitions; activities call business services
  infra_services/            paperclip, github_app, temporal, litellm, context engine clients (*_service.py)
  database/postgres/repository/<capability>/   database/postgres/schema/
  models/<capability>_models.py   every Pydantic model
```

Rules applied as written: pyright `strict` from the first commit; Pydantic v2 at every boundary, never a `dict`; closed vocabularies as `StrEnum` with a `Type` suffix; no `Any`, no `# type: ignore`, no `TYPE_CHECKING` imports; `injector` with `@inject`; loguru; Alembic; Poetry, Black, Ruff.

**Extension points** are typed `Protocol`s with a `StrEnum` registry, bound in `di/modules/`: building blocks (AD-3), context engines (REQ-36), outcome checks per gate class, merge strategy (AD-8). Adding one is a class, an enum value and a binding; pyright flags every unhandled `match`.

**Import contracts** (import-linter, CI): the rules' layer contract (`api` → `business_services` → repository → schema); `engine` imports no IO layer; `workflows` imports `business_services` and `models` only; the `mandate_context` entrypoint imports only `models`, `engine` and its own infra client.

**Upstream change:** one pull request to `python-services-rules` adds `workflows/` (durable workflow definitions) to the standard package table, since the rules have no slot for it today.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
