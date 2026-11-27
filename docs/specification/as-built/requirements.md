# As-built: requirements status

One row per requirement. Each pull request that changes a requirement's status updates its row in the same PR (same-PR discipline). Statuses: `not started`, `implemented`, `unit-tested`, `live-verified`.

Requirement text lives in `mandate-meta/prd/INIT-MANDATE-001.md`; this table tracks status only.

| Requirement | Wave | Status | Evidence (PR, test, run) |
| --- | --- | --- | --- |
| REQ-01 | W1 | not started | |
| REQ-02 | W1 | not started | |
| REQ-39 | W1 | not started | |
| REQ-40 | W1 | implemented | Mandate's Paperclip identity only (TASK-W0-07): its client acts inside its own run, refuses an unpinned release, and cannot create agents or skills or assign tasks; proved by tests/contract/paperclip against the run stack. Deciding gates comes later |
| REQ-42 | W1 | not started | |
| REQ-43 | W1 | not started | |
| REQ-54 | W1 | implemented | Decision entries (TASK-W0-04): the ledger writer stores actor, role, rung, options offered, choice, reasons, evidence, target version, workflow version, model version and decided_at in the hashed payload, with the version stamp (policy revision, skills, Mandate release and the rest) beside it. The stamp has no workflow or model version, so the decision record carries them. Unit-tested on the pure record and entry; no gate writes decisions yet |
| REQ-55 | W1 | implemented | Database protection (TASK-W0-03): schema per capability, mandate_app limited to INSERT and SELECT on ledger.entries, append-only trigger; proved by tests/journeys/database_roles. Hash chain and corrections (TASK-W0-04): entries link by previous hash from a genesis hash, verification finds any edited, deleted, inserted or reordered entry (property tests; entries cut off the end or a re-hashed suffix need the head hash from a checkpoint kept outside the table, which the signed daily checkpoint task adds); a correction is a new entry naming the original by hash; appends take an advisory lock and a unique index on previous_hash refuses a fork, proved by tests/integration/ledger against real Postgres. recorded_at is not covered by the hash. The service runs as mandate_app (ADR-020): the image migrates with the owner set (POSTGRES_MIGRATION_*), then starts the service without those keys, and a missing key of either set stops the start by name; proved by tests/journeys/database_roles/test_service_runs_as_the_app_role.py (session user, no ledger rewrite, no owner key or usable owner password in the service environment). Outbox and inbound (TASK-W0-05): a state change, its ledger entry and its outbox message commit in one transaction (the ledger writer has append_decision_in and append_correction_in that join the caller's transaction, lock and head checks included), and a failure at any step leaves none of the three; the writer refuses to append on a head that does not link back to genesis; outbox messages carry an idempotency key derived from the work item, destination and step, the dispatcher delivers each due message in its own transaction with a row lock, retries failures with a doubling wait up to 15 minutes, and sends the key with every send so a receiver that honours it applies a repeated send once (delivery is at least once); inbound.events keeps one row per source and event id and ignores a repeat, and mandate_app may only insert and select there; proved by tests/integration/outbox and tests/integration/ledger against real Postgres. No transport to a real destination exists yet, so the receiver in those tests applies each key once. Outstanding: the owner's password still sits in the container configuration as a value, not a file secret (ADR-019); the lab itself is covered by the runner's rehearsal, not by a journey |
| REQ-60 | W1 | not started | |
| REQ-61 | W1 | not started | |
| REQ-62 | W1 | not started | |
| REQ-63 | W1 | not started | |
| REQ-86 | W1 | not started | |
| REQ-103 | W1 | not started | |
| REQ-108 | W1 | not started | |
| REQ-118 | W1 | not started | |
| REQ-120 | W1 | unit-tested | scripts/record_review_decision.py writes a decision as a ledger-format JSON line to a local file; tests/unit/test_review_decision.py (TASK-W0-01). The import into the ledger is W1 |
| REQ-121 | W1 | not started | |
| REQ-122 | W1 | not started | |
| REQ-03 | W2 | not started | |
| REQ-04 | W2 | not started | |
| REQ-05 | W2 | not started | |
| REQ-06 | W2 | not started | |
| REQ-08 | W2 | not started | |
| REQ-09 | W2 | not started | |
| REQ-10 | W2 | not started | |
| REQ-11 | W2 | not started | |
| REQ-12 | W2 | not started | |
| REQ-13 | W2 | not started | |
| REQ-21 | W2 | not started | |
| REQ-22 | W2 | not started | |
| REQ-23 | W2 | not started | |
| REQ-24 | W2 | not started | |
| REQ-25 | W2 | not started | |
| REQ-26 | W2 | not started | |
| REQ-27 | W2 | not started | |
| REQ-28 | W2 | not started | |
| REQ-29 | W2 | not started | |
| REQ-30 | W2 | not started | |
| REQ-31 | W2 | not started | |
| REQ-32 | W2 | not started | |
| REQ-33 | W2 | not started | |
| REQ-34 | W2 | not started | |
| REQ-35 | W2 | not started | |
| REQ-38 | W2 | not started | |
| REQ-104 | W2 | not started | |
| REQ-41 | W3 | not started | |
| REQ-44 | W3 | not started | |
| REQ-59 | W3 | not started | |
| REQ-64 | W3 | not started | |
| REQ-65 | W3 | not started | |
| REQ-67 | W3 | not started | |
| REQ-72 | W3 | not started | |
| REQ-78 | W3 | not started | |
| REQ-14 | W4 | not started | |
| REQ-15 | W4 | not started | |
| REQ-16 | W4 | not started | |
| REQ-20 | W4 | not started | |
| REQ-68 | W4 | not started | |
| REQ-99 | W4 | not started | |
| REQ-100 | W4 | not started | |
| REQ-101 | W4 | not started | |
| REQ-45 | W5 | not started | |
| REQ-58 | W5 | not started | |
| REQ-75 | W5 | not started | |
| REQ-76 | W5 | not started | |
| REQ-77 | W5 | not started | |
| REQ-79 | W5 | not started | |
| REQ-82 | W5 | not started | |
| REQ-84 | W5 | not started | |
| REQ-85 | W5 | not started | |
| REQ-87 | W5 | not started | |
| REQ-88 | W5 | not started | |
| REQ-89 | W5 | not started | |
| REQ-93 | W5 | not started | |
| REQ-94 | W5 | not started | |
| REQ-95 | W5 | not started | |
| REQ-107 | W5 | not started | |
| REQ-109 | W5 | not started | |
| REQ-110 | W5 | not started | |
| REQ-111 | W5 | not started | |
| REQ-07 | W6 | not started | |
| REQ-46 | W6 | not started | |
| REQ-47 | W6 | not started | |
| REQ-48 | W6 | not started | |
| REQ-49 | W6 | not started | |
| REQ-50 | W6 | not started | |
| REQ-51 | W6 | not started | |
| REQ-52 | W6 | not started | |
| REQ-53 | W6 | not started | |
| REQ-56 | W6 | not started | |
| REQ-57 | W6 | not started | |
| REQ-73 | W6 | not started | |
| REQ-74 | W6 | not started | |
| REQ-83 | W6 | not started | |
| REQ-102 | W6 | not started | |
| REQ-105 | W6 | not started | |
| REQ-106 | W6 | not started | |
| REQ-119 | W6 | not started | |
| REQ-17 | W7 | not started | |
| REQ-18 | W7 | not started | |
| REQ-19 | W7 | not started | |
| REQ-66 | W7 | not started | |
| REQ-70 | W7 | not started | |
| REQ-71 | W7 | not started | |
| REQ-36 | W8 | not started | |
| REQ-37 | W8 | not started | |
| REQ-80 | W8 | not started | |
| REQ-81 | W8 | not started | |
| REQ-112 | W8 | not started | |
| REQ-69 | W9 | not started | |
| REQ-90 | W9 | not started | |
| REQ-91 | W9 | not started | |
| REQ-92 | W9 | not started | |
| REQ-113 | W9 | not started | |
| REQ-114 | W9 | not started | |
| REQ-115 | W9 | not started | |
| REQ-116 | W9 | not started | |
| REQ-96 | Programme two | not started | |
| REQ-97 | Programme two | not started | |
| REQ-98 | Programme two | not started | |
| REQ-117 | Programme two | not started | |
