# Specification

The rules' truth hierarchy for this repo (`.cursor/rules/spec-driven-development.mdc`):

| Order | Where | Answers |
| --- | --- | --- |
| 1 | `.cursor/rules/` | How we build (constitution, never edited here) |
| 2 | `product/` | What this repo builds |
| 3 | `adr/` | Why it is built this way |
| 4 | `as-built/` | What is live, per requirement |

Programme-level documents live in `mandate-meta`: `prd/INIT-MANDATE-001.md` (product PRD), `prd/INIT-MANDATE-001-engineering.md` (engineering-ready PRD), `planning/mandate-vision.md` and `Implementation-Plan-INIT-MANDATE-001.md` (waves and the WorkManifest).

Every pull request updates spec, tests and as-built together.
