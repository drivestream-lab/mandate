# As-built: requirements status

One row per requirement. Each pull request that changes a requirement's status updates its row in the same PR (same-PR discipline). Statuses: `not started`, `implemented`, `unit-tested`, `live-verified`.

Requirement text lives in `mandate-meta/prd/INIT-MANDATE-001.md`; this table tracks status only.

| Requirement | Wave | Status | Evidence (PR, test, run) |
| --- | --- | --- | --- |
| REQ-01 | W1 | implemented | Programme from configuration (TASK-W0-09): the meta repo's config/programme.yaml is read at a commit and a Paperclip project is created for it (repos, roles with their agents, decision owner per gate class, pinned workflow, starting rung); a repeat makes no second project; proved by tests/journeys/onboard_a_programme against the run stack and the sandbox meta repo. No budget link yet; the GitHub reader is a test-side implementation until the GitHub App service lands |
| REQ-02 | W1 | implemented | Readiness (TASK-W0-09): every role's agent exists and is usable, every repo is reachable, the pinned workflow loads (the meta repo's harness pin names a skills repo and tag, and that tag's workflow.yaml is read and parsed; a missing tag, file or unparseable workflow fails), and Mandate's own agent is checked for agent creation, task assignment (interaction permissions) and the company skill-policy deny rule, evaluated as the pinned Paperclip does (first rule by priority, allow or deny); each failure names its cause and require_ready stops a start; proved by tests/journeys/onboard_a_programme. Nothing calls require_ready yet: the start path comes later |
| REQ-39 | W1 | implemented | The brief text (what is decided, options with impact, recommendation and why, evidence bound to the head commit, what follows) posted on a sandbox pull request (TASK-W0-10); tests/unit/engine/gates, tests/journeys/decide_blind_first. Delivery to real gate pull requests and the signoff artifacts are W1 |
| REQ-40 | W1 | unit-tested | Mandate reads a gate's signoff on the head and decides nothing; the check is re-run over every open pull request into develop and main by recheck_open_gates (a pull request it cannot read is logged and returned as an escalation; no recorded escalation channel exists yet), which is not scheduled until the walking-skeleton workflow (W1-05) calls it, so between evaluations a status stays on its sha; the check is tied to the merge (base branch, repository and pull request in the attestation, no second open pull request on the head), and the attestation must carry initiative, head, digests, artifact paths, gate, repo and pull request and, when the pull request has upstream pull requests, each of them with the head the holder reviewed against (TASK-W1-02), and nothing else: the signer must hold the gate at its rung, and Mandate's own App approving does not count (TASK-W1-01); tests/unit/engine/gates, tests/journeys/sign_a_gate. Applying the signoff at L2 and L3 comes later. Paperclip identity limits (TASK-W0-07) still hold |
| REQ-42 | W1 | live-verified | A decision covers only the exact head: a push after signoff leaves the check failing on the new head and Mandate records a void (an entry by Mandate, recorded under the actor mandate[app], which no GitHub login can be, and the role `<gate label> revised`, keyed on the gate's own label and not on its display labels; it names the voided head and the ids of every Approve on that head, by any reviewer, and each signoff each new head voids is its own entry) and applies the gate's -revised label; the ledger decides and a removed label changes nothing; a head that carries a void passes only on an Approve review that no void on that head names (a signoff is looked for among the Approves no void names, so a second holder's new Approve restores it), so a branch moved back to a commit that was signed before still fails until the holder approves again (no clock comparison); an Approve whose body was ever edited, by anyone (GraphQL lastEditedAt or any edit revision, a review whose history cannot be read counts as edited), is never pinned: the edit is recorded and the check fails until the holder approves again (GitHub lets another account with write access rewrite a review body, shown live); otherwise the first check pins the SHA-256 of the exact body as Mandate's own ledger record, and a later check whose live body hashes differently fails with the edit recorded; Mandate removes -revised and -stale when the signoff on the current head passes (TASK-W1-02). The void label names come with the gate rule (spec-lgtm gives spec-revised and spec-stale, wave-accepted gives wave-revised and wave-stale, or the rule names its own); tests/unit/engine/gates, tests/journeys/work_changes_after_approval (including a signed wave-accepted gate). A void is recorded only for a signoff Mandate had recorded, and only when a check ran on the new head
| REQ-43 | W1 | unit-tested | A gate nobody signed fails mandate/gate-decision with its reason; no timeout or default exists in the rules; at L0 only a person's Approve counts (an App's is refused with that reason); any read or ledger fault once the head is known posts failure, and a success is read again and withdrawn if it no longer holds (TASK-W1-01); tests/unit/engine/gates, tests/journeys/sign_a_gate |
| REQ-54 | W1 | implemented | Decision entries (TASK-W0-04): the ledger writer stores actor, role, rung, options offered, choice, reasons, evidence, target version, workflow version, model version and decided_at in the hashed payload, with the version stamp (policy revision, skills, Mandate release and the rest) beside it. The stamp has no workflow or model version, so the decision record carries them. Unit-tested on the pure record and entry; no gate writes decisions yet |
| REQ-55 | W1 | implemented | Database protection (TASK-W0-03): schema per capability, mandate_app limited to INSERT and SELECT on ledger.entries, append-only trigger; proved by tests/journeys/database_roles. Hash chain and corrections (TASK-W0-04): entries link by previous hash from a genesis hash, verification finds any edited, deleted, inserted or reordered entry (property tests; entries cut off the end or a re-hashed suffix need the head hash from a checkpoint kept outside the table, which the signed daily checkpoint task adds); a correction is a new entry naming the original by hash; appends take an advisory lock and a unique index on previous_hash refuses a fork, proved by tests/integration/ledger against real Postgres. recorded_at is not covered by the hash. The service runs as mandate_app (ADR-020): the image migrates with the owner set (POSTGRES_MIGRATION_*), then starts the service without those keys, and a missing key of either set stops the start by name; proved by tests/journeys/database_roles/test_service_runs_as_the_app_role.py (session user, no ledger rewrite, no owner key or usable owner password in the service environment). Outbox and inbound (TASK-W0-05): a state change, its ledger entry and its outbox message commit in one transaction (the ledger writer has append_decision_in and append_correction_in that join the caller's transaction, lock and head checks included), and a failure at any step leaves none of the three; the writer refuses to append on a head that does not link back to genesis; outbox messages carry an idempotency key derived from the work item, destination and step, the dispatcher delivers each due message in its own transaction with a row lock, retries failures with a doubling wait up to 15 minutes, and sends the key with every send so a receiver that honours it applies a repeated send once (delivery is at least once); inbound.events keeps one row per source and event id and ignores a repeat, and mandate_app may only insert and select there; proved by tests/integration/outbox and tests/integration/ledger against real Postgres. No transport to a real destination exists yet, so the receiver in those tests applies each key once. Database passwords reach the container as files read by path (ADR-019): POSTGRES_PASSWORD_FILE for the app, POSTGRES_MIGRATION_PASSWORD_FILE for the owner; the entrypoint (root) runs the migration with the owner's file, then drops to the app user, which cannot read it; POSTGRES_PASSWORD and POSTGRES_MIGRATION_PASSWORD are refused, and docker inspect and /proc/1/environ show no password (proved by the same journey). Outstanding: the lab itself is covered by the runner's rehearsal, not by a journey |
| REQ-60 | W1 | not started | |
| REQ-61 | W1 | not started | |
| REQ-62 | W1 | not started | |
| REQ-63 | W1 | not started | |
| REQ-86 | W1 | unit-tested | Gates are signed on their pull request; the service has no route that writes a decision (TASK-W1-01); tests/unit/api. The control tower links come later |
| REQ-103 | W1 | implemented | The call is sealed in the ledger before the brief is posted, absent from the pull request at intent and design gates, shown at verification and housekeeping gates, and revealed only behind an explicit signoff-recorded input (TASK-W0-10); tests/journeys/decide_blind_first reads the pull request back. Reading the holder's signoff itself is W1 |
| REQ-108 | W1 | not started | |
| REQ-118 | W1 | implemented | The deciding role's structured call (option, reasons, evidence cited) only (TASK-W0-08): a scripted deciding role on Paperclip's process adapter returns it, checked against the shared model, and an output that fails its schema counts as missing; proved by tests/journeys/test_agents against the run stack. Sealing, the one retry and the no-call record are in TASK-W0-10 (tests/journeys/decide_blind_first) |
| REQ-120 | W1 | unit-tested | scripts/record_review_decision.py writes a decision as a ledger-format JSON line to a local file; tests/unit/test_review_decision.py (TASK-W0-01). The import into the ledger is W1 |
| REQ-121 | W1 | live-verified | Non-merge decisions are asked as a review on the pull request or a Paperclip question, the deciding role's call sealed first, recorded with the holder (one entry per holder, role and head; a changed verdict is a correction naming the earlier entry; the look-up and write share the ledger's chain lock), and never block; the Paperclip route is proved live with the board user answering (TASK-W1-01); tests/unit/engine/gates, tests/journeys/sign_a_gate. Stale marking and recorded no's (TASK-W1-02) run only when the caller passes links to evaluate_and_post and recheck_open_gates, and nothing passes them yet: the walking-skeleton workflow (W1-05) must build them from the work item and schedule recheck_open_gates. Stale: the Approve's attestation names each upstream pull request with the head the holder reviewed against; a linked upstream that is not named, or is named at another head than it has now, makes the signoff stale (the baseline is the signer's, never what Mandate sees at its first check); Mandate records a stale void for that head (role `<gate label> stale`, naming the Approve review it covers), applies the gate's -stale label and fails the check; the holder approves again, against the new upstream head. A recorded no belongs to its decision (recorded under a role naming the decision's gate; the gate id is required wherever a decision is recorded) and its holder: a linked decision fails the downstream merge while that holder's newest recorded decision across the artifact's heads is a no, so revising is not enough until decided again; only that holder's later approve lifts it, and another holder's approve of the same artifact does not; tests/journeys/work_changes_after_approval |
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
