# ADR-017: Testing without fakes

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-5 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Mandate is tested against the real systems; nothing fakes Paperclip, GitHub or the agents. Where a condition cannot be produced live, it is validated by a unit test on the pure function that handles it.

| Situation | How it is tested |
| --- | --- |
| Rules (promotion, demotion, policy, ledger chain, wave planning) | Unit, property and simulation tests on `engine/` with an injected clock |
| Outages mid-flow | Network fault proxy (Toxiproxy) between Mandate and real Paperclip and GitHub; Mandate workers killed mid-step |
| Duplicate, reordered or lost events | Real captured Paperclip events replayed into Mandate's ingest twice, out of order or with one missing |
| Races (head moves before merge) | Test-only pause points in Mandate, then a real push. Pause points are a typed extension, off by default and refused at startup in production |
| Hostile cases | Real negatives: a genuine attestation from the wrong workflow, a real PR editing the protected test path, a real decision attempt from an app identity |
| Parallel runs | An ephemeral Paperclip from the pinned image per run, with its own database, in a local Compose stack; GitHub work namespaced per run; a dedicated test installation of Mandate's App |
| Role agents | Deterministic real agents: real Paperclip agent identities whose adapter returns scripted, schema-checked outputs without calling a model |
| GitHub-shaped errors (for example a 502 on merge) | Unit test on the pure response-handling function; the live run proves the network-fault equivalent |

Layout: `tests/unit/`, `tests/properties/`, `tests/simulation/` (pure, every push); `tests/journeys/` and `tests/fault/` (live, every PR); `tests/verify/` (sandbox and Conduit stages). Every test carries its REQ ids and the build fails if a requirement has none.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
