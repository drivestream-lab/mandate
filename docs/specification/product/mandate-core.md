# Mandate core: product specification

> This is the `mandate` repo's slice of INIT-MANDATE-001. Programme-level intent lives in `mandate-meta/prd/INIT-MANDATE-001.md` (product PRD, requirement text) and `mandate-meta/prd/INIT-MANDATE-001-engineering.md` (engineering-ready PRD). Where this file and those disagree, raise it; do not pick one silently. Decisions are in `../adr/`; status per requirement is in `../as-built/requirements.md`.

## What this repo builds

Mandate core: the API and plugin backend, the generic runner and building blocks, gates, deciding-role calls and autonomy, policy, release and merge control, measures, escalation, the sweep and timers, the ledger and checkpoint job, and the `mandate-context` gateway as its own package and container (ADR-013, ADR-014). It does not build the control tower UI (`mandate-control-tower`) or the verification workflow (`mandate-verify`), but it owns their contracts on Mandate's side.

## Current wave: W1, walking skeleton and project layout

W1 builds the full project layout with one gate running through it: the PRD merge into `develop` on `mandate-sandbox-meta`, signed at L0 blind-first on its pull request with the deciding role's call sealed in the ledger, Mandate's required check `mandate/gate-decision` allowing the merge only on a matching signoff, then one wave on `mandate-sandbox-svc` with run-signed evidence and the exact commit merged, the ledger recording each decision. Tasks are in `mandate-meta/Implementation-Plan-INIT-MANDATE-001.md` section 9.

| Id | Requirement | Journeys |
| --- | --- | --- |
| REQ-01 | A programme is created on a Paperclip project from the programme configuration Launchpad keeps in its meta repo: repos, role cards and the agents filling them, a decision owner per gate class, workflow version, budget link and a starting rung per gate | J-01 |
| REQ-02 | Before any work starts, Mandate shows that every role in the workflow has a usable agent, GitHub access works for every repo and the pinned workflow loads; each failure is shown with its cause | J-01 |
| REQ-39 | Every gate shows a brief on its pull request: what is decided, options with their impact, the recommendation and why, evidence bound to the head commit, and what happens once it is signed off | J-03 to J-06 |
| REQ-40 | A gate is decided only by whoever holds it at its current rung, under their own identity; nobody decides for someone else. At L2 and L3 Mandate's app carries out the deciding role's recorded decision on GitHub (label, approval, merge) but never decides; no app or service identity decides | J-06 |
| REQ-42 | A decision covers only the exact version reviewed; if the target changes, the approval no longer counts and the gate reopens | J-09 |
| REQ-43 | A gate held by a human never moves without that human's decision: no default, no fallback option, no acceptance on timeout | J-06, J-21 |
| REQ-54 | Every decision records actor, role, rung, options offered, choice, reasons, evidence, target version, and workflow, policy, skill, model and Mandate versions | J-23 |
| REQ-55 | Ledger entries cannot be changed or deleted; a correction is a new entry referencing the original | J-23 |
| REQ-60 | Verification builds the exact commit into a clean environment with seeded data and records the version of every service in an environment manifest | J-06 |
| REQ-61 | A wave is releasable only with an acceptance test report, environment manifest and commit binding for the same commit; traces, declared database checks and requirement coverage become mandatory when policy says so | J-06 |
| REQ-62 | Partial or truncated evidence counts as missing | J-06 |
| REQ-63 | A gate is a merge into develop, or from develop into main. The merge is allowed only when Mandate's required check passes on the current head: the signoff (label, approval with attestation, pull request ready) matches that head, its signer held the gate at its rung, the decision is in the ledger, and for a wave the run-signed evidence verifies. A push after signoff voids it. At L0 the human signs and the merger the workflow names merges; at L2 and L3 the deciding role signs and Mandate's app applies the signoff and merges the exact commit. Parallel waves re-verify against the latest develop. The single exception is REQ-109 | J-06, J-09 |
| REQ-86 | Gates are signed on their pull request; questions, escalations and work happen in Paperclip's inbox and threads; the control tower links to both and offers no second place to decide | J-06 |
| REQ-103 | At intent and design gates held by a human, the deciding role's call is sealed in the ledger and never appears on the pull request before the human signs off; it is revealed once the signoff is recorded. At verification and housekeeping gates the recommendation is shown with the evidence | J-16 |
| REQ-108 | Release evidence is produced and signed by the verification run's own identity, with a hash for every artifact. The run executes exactly the protected test set fixed at spec sign-off, less tests quarantined on the record; any other set counts as missing evidence. The verifier agent interprets the evidence but cannot produce or change it | J-06 |
| REQ-118 | Each gate class has a deciding role (intent, design, release, housekeeping decider), never the author or challenger of the work at that gate. It records its own blind call at every decision from the first one; that record, not the author's recommendation, is what earns it the gate | J-16, J-17 |
| REQ-120 | Until Mandate's own development joins as a programme, Claude Code builds Mandate under human review, with each review decision recorded in the ledger's own format; those records are imported when Mandate's programme is onboarded, so its history is complete from the first decision | J-28 |
| REQ-121 | Only merges block. Every other decision (technical review, clarification checkpoints, triage, hiring) is recorded in the ledger with its holder and counts toward promotion, but no work waits on it. When an upstream artifact changes after a signoff, the downstream signoff is marked stale and must be signed again on the new head. A non-merge decision is made where its artifact lives: as a review on the pull request when there is one (technical review, clarification checkpoints), otherwise as a Paperclip question (triage, hiring, adding a repo), with the deciding role's call sealed first on both. A recorded no does not stop work, but the next merge gate downstream of that artifact fails Mandate's check until the artifact is revised and decided again or the holder withdraws the no | J-06, J-09 |
| REQ-122 | Within one sweep, Mandate detects any merge into develop or main whose head had no passing gate check, and any change to a gate ruleset or branch protection not made by a decided Launchpad run. It records each as a policy breach, escalates to the owner, and opens a revert pull request that goes through the gate like any other. On Mandate's own repos a named human's emergency merge is the recorded exception (REQ-109) | J-06, J-28 |

## Capabilities to packages, with negative paths

Each capability has one owning package in `mandate` (or a separate repo). Negative paths marked ADH are failures the old system had; each becomes an acceptance test.

| Capability | Owner | Negative paths that must be impossible |
| --- | --- | --- |
| CAP-01 Programme setup and growth | `programmes` | Work starting before every role, repo and the workflow are usable; a repo joining before Launchpad's readiness check passes |
| CAP-02 Role catalogue and hiring | `roles` | An agent acting outside its role or programme; a role card counting toward promotion before its two-setup proof |
| CAP-03 Outline intake | `intake` | An initiative without an accepted outline; a resubmitted outline creating a second initiative |
| CAP-04 Kinds and triage | `intake` | A new capability entering as an enhancement unchallenged; a kind change without a recorded reason |
| CAP-05 Workflow execution | `runner` | A transition the pinned workflow does not define; work moving to a newer workflow mid-flight; a contract needing a block version Mandate lacks running anyway |
| CAP-06 Engineering readiness | `readiness` | Spec work starting before the readiness gate passes; a product question answered by anyone but the PM role |
| CAP-07 Shared codebase context | `mandate-context` | An answer without repo, path and commit; a fallback to level 0 not recorded |
| CAP-08 Gate decisions | `gates` | Anyone deciding on work they authored or challenged; an app identity deciding (ADH: second app pre-approving); default, fallback or timeout acceptance (ADH: first allowed option, accepted by default); a decision applied to a changed target; the deciding role's call visible before the human chooses at a blind-first gate |
| CAP-09 Autonomy management | `autonomy` | Promotion on anchored agreement at verification and housekeeping gates; an agent promoting its own gate; promotion from emergency merges; a rung carried across programmes |
| CAP-10 Ledger and outcomes | `ledger` | An entry changed or deleted without the chain breaking against the last checkpoint; a clean outcome counted for a change nobody exercised |
| CAP-11 Governed release | `release` | A merge of a commit other than the verified one (ADH: merge without the verified commit); evidence the run did not sign; a test set other than the protected one; truncated evidence accepted (ADH: evidence cut to fit); a bypass on any repo but Mandate's own |
| CAP-12 GitHub issue copies | `github` | Two issues for one work item (ADH: matching by title); a GitHub edit changing Mandate state |
| CAP-13 Rollout and outcomes | `release` | A rollout step without live health evidence; a revert not linked to the decisions behind it |
| CAP-14 Policy | `policy` | A decision without a policy revision; a programme loosening a company ceiling |
| CAP-15 Measures and evolution | `measures` | A measure without a version stamp; a process change released without replay or canary |
| CAP-16 Control tower | `mandate-control-tower`, `api` | A decision taken from the control tower; a viewer seeing another programme |
| CAP-17 Escalation | `escalation` | Escalation to a party to the dispute; an escalation dropped silently |
| CAP-18 Resilience | `runner`, `ops` | A step lost, repeated or skipped across restart or outage; a gate decided while Paperclip or GitHub is unreachable |
| CAP-19 Audit export | `ledger`, `api` | An export that omits missing evidence instead of marking it; an export an auditor cannot verify against a checkpoint |
| CAP-20 Multi-programme | `programmes` | Work visible across programmes; a shared specialist's record merged across programmes |
| CAP-21 Operating Mandate | `ops` | An upgrade changing pinned work; a restore that loses in-flight work; Mandate failing silently |

## Seams and contracts

Every seam is a contract with its own tests. What crosses it is fixed here; field-level schemas are the spec's job.

| Id | Seam | What crosses it | Guarantees Mandate relies on or gives | Requirements |
| --- | --- | --- | --- | --- |
| CTR-01 | Mandate to Paperclip: issues and execution policy | Create and update issues for steps and sealed-call requests; write governed fields; read current state; every write inside a run Mandate obtains by waking its own agent | Every write carries an idempotency key; Mandate refuses to run against an unrecognised Paperclip release | REQ-21, 23, 40, 43 |
| CTR-02 | Mandate to Paperclip: decisions | Questions only (product questions, escalation choices, and non-merge decisions with no pull request: triage, hiring, adding a repo): title, body, options, expiry within Paperclip's 30-day limit, idempotency key; read the choice and decider. Merge gates are not decided here | The decision's signed spec snapshots what was asked | REQ-39, 42, 103 |
| CTR-03 | Plugin to Mandate: event relay | The subset of Paperclip events Mandate needs: issue created, updated and released; comments; approval decided; agent runs started, finished, failed; cost events; budget incidents | At least once, unordered: Mandate deduplicates by event id and treats events only as hints to read state | REQ-90 to 92 |
| CTR-04 | Mandate to agents, through Paperclip | Step work and sealed-call requests as issues assigned to role agents, with structured inputs; results as documents or comments in a fixed schema per artifact type; the deciding-role call schema: option, reasons, evidence cited | Output that fails its schema counts as missing; untrusted content arrives marked (REQ-104) | REQ-25, 104, 118 |
| CTR-05 | Mandate and GitHub, through Mandate's App | Read pull requests, reviews, labels, ready state and workflow runs (polled; webhooks built and kept off); post the brief and the required check mandate/gate-decision; at L2 and L3 apply the gate's label, attested Approve and ready state for the deciding role and merge with sha pinned to the head; update a branch; create and update issue copies | GitHub refuses a merge into develop or main without the check; the check is tied to a head commit, so a push voids it | REQ-63, 68 to 70 |
| CTR-06 | Verification workflow to Mandate: evidence bundle | Test report, environment manifest, commit, protected test-set digest, quarantine list in force, signed with the `mandate-verify` workflow's identity | Mandate verifies signer workflow and pinned commit, the target commit and the test-set digest; anything else counts as missing evidence | REQ-60 to 62, 108 |
| CTR-07 | Delivery contract to Mandate | A versioned `prayog-skills` release: workflows as arrangements of building blocks, required block versions, gate classes, kinds and attributes, id conventions, outline standard, readiness contract | Mandate refuses a contract that needs a block version it lacks | REQ-11, 22, 24, 32 |
| CTR-08 | Launchpad configuration to Mandate | The meta repo's programme, governance (repos, stacks) and service catalogue files at a commit; Launchpad's readiness result for a new repo | Read-only; a repo joins only when its readiness check passes | REQ-01, 99, 100 |
| CTR-09 | Mandate to control tower plugin | Read views scoped to the viewing user; policy edits from the settings page | No endpoint decides a gate | REQ-82 to 87 |
| CTR-10 | Context service | Agents ask over MCP; answers cite repo, path, lines and commit; the service sends Mandate a usage record per answer with engine, level and any fallback | Answers never judge; a fallback to level 0 is recorded | REQ-34 to 38 |
| CTR-11 | Mandate core and Temporal | Step workflow inputs carry work item, step and idempotency key; results come back to Mandate in one transaction with the state change | A step run twice has one effect | REQ-90, 91 |

## Conceptual data model

What Mandate stores, at the level a builder needs to agree on before the spec. Tables, columns and indexes belong to the spec.

| Entity | Holds | Notes |
| --- | --- | --- |
| Programme | Paperclip project, meta repo, calendar and time zone, decision owners per gate class | Created from Launchpad configuration |
| Repo | Name, stack, readiness status, date joined | Joins only after Launchpad's readiness check |
| Role card, hire | Versioned role definition; the agent setup filling it on a programme; probation and two-setup proof status | Hiring is a design gate |
| Work item | Kind, attributes, pinned contract and block versions, current position (block and state), links to Paperclip issue and GitHub issue | One row per item; the runner's state lives here |
| Gate | Class, rung, ceiling, deciding role, minimum-stay clock, hold-for-human flag | Per programme, per gate, per kind |
| Gate opening | One occasion a gate is decided: the PR and its head commit, brief hash, signoff artifacts (label, approval, attestation, ready state), check id, status | Opens, seals, decides, reveals, closes |
| Sealed call | Deciding role's option, reasons and cited evidence, hashed into the ledger before the human decision opens | Revealed after the choice |
| Evidence bundle | References and hashes of report, manifest, test-set digest, attestation; retention clock | Content expires at 30 days or at the gate's next promotion; hashes stay |
| Ledger entry | Sequence, previous hash, own hash, type (decision, sealed call, promotion, demotion, emergency merge, policy change, escalation outcome), payload, version stamp | Append-only; separate from working state |
| Checkpoint | Chain head hash, policy hash, signature, commit in `mandate-meta` | Daily |
| Policy revision | Typed values, author, reason, effective from | Every decision cites one |
| Timer | What fires, when, for which work item | Fired by the sweep |
| Outbox message | Action leaving Mandate, idempotency key, status | Written in the same transaction as the state change |
| Inbound event | Source, event id, received at | Deduplication only |
| Product question | Question, scenario, example, recommendation, blocking flag, answer, round | Readiness stage |
| Escalation | Trigger, target agent then humans, resolution | Agent outside the dispute first |
| Step run measure | Times, waiting time, human minutes, rework rounds, cost, version stamp | Feeds measures and DORA benchmark |
| Context answer record | Question type, repo, commit, engine, level, fallback, latency | From the context service |

## Key flows

### Gate lifecycle

Gate lifecycle at L0 (a gate is a merge into `develop`, or `develop` into `main`):

1. **PR ready to sign.** The gate's pull request exists with the artifact at its head (PRD, spec, wave or closure purge).
2. **Brief posted.** Mandate posts the brief on the pull request, bound to the head commit.
3. **Call requested.** The deciding role gets the brief, without the author's recommendation.
4. **Call sealed, never on the PR.** Its hash goes into the ledger before the holder signs; nothing of it appears on the pull request.
5. **Holder signs.** On GitHub, under their own identity: the gate's label, an Approve carrying the attestation, and the pull request marked ready.
6. **Mandate checks.** The signoff matches the head, the signer held the gate at its rung, and for a wave the run-signed evidence verifies.
7. **Recorded and revealed.** The decision goes into the ledger; the call is revealed on the pull request; agreement is counted.
8. **Merge allowed.** Mandate posts `mandate/gate-decision` as success on that head, and the workflow's merger merges. A push after signoff voids it.

A gate is a merge into `develop` (or `develop` into `main`), signed on its pull request. At L0 the human holder signs on GitHub with the gate's label, an Approve carrying the attestation and the PR marked ready; the deciding role's call was sealed in the ledger before and is never shown on the PR until the signoff is recorded. At L2 the deciding role signs, Mandate's App applies the three artifacts, and the veto window runs before the check is posted; at L3 the check is posted at once. A push after signoff voids it (`-revised`); an upstream change marks it `-stale`. Work before the merge is never held: agents keep going, and a sent-back PR is ordinary rework.

### Release of a wave

1. The coder opens the wave's draft PR; its caller workflow runs `mandate-verify` at the pinned tag on that commit.
2. Mandate fetches the attested evidence bundle and verifies the signer workflow, commit and test-set digest. Anything that fails counts as missing evidence and goes back to the coder as findings.
3. Mandate posts the brief on the PR (gate lifecycle above). The verifier's interpretation is part of the brief.
4. The holder signs (`wave-accepted`, attested Approve, ready). Mandate checks the signer held the gate, the artifacts match the head and the evidence verifies, records the signoff, and posts `mandate/gate-decision`.
5. The merger merges into `develop` (at L2 and L3, Mandate's App, with `sha` pinned to the head). If `develop` moved, the branch is updated, verification reruns, and a new signoff is needed only if the evidence changed.
6. Mandate records the merge in the ledger, updates the issue copy, links deployment status, and the runner starts the next wave.

### Promotion and demotion

- After every closed gate opening and every outcome that lands, Mandate re-evaluates that gate against the policy revision in force: decisions at the rung, minimum stay, critical misses, and the evidence its class counts (agreement plus clean exercised outcomes at intent and design gates; clean exercised outcomes only at verification and housekeeping gates).
- A pass promotes one rung (L0 to L2 at intent and design gates), writes a ledger entry with the evidence, hands the gate to its deciding role, and informs the owner and decision owner.
- An overrule or failed outcome demotes one rung at once; a policy breach drops the gate to L0. Emergency merges are excluded from all of it.

### Recovery

- On restart, the runner reads each work item's row and carries on; in-flight Temporal steps resume; the outbox resends anything not yet acknowledged; idempotency keys make every repeat harmless.
- The sweep compares expected and actual state in Paperclip and GitHub every minute and fires due timers. While either platform is unreachable, nothing advances and no gate is decided.

### Emergency path (Mandate's own repos only)

- A named human merges directly in GitHub using the bypass only they hold. When Mandate returns, the sweep finds the merge, records it in the ledger with its evidence, and opens a follow-up review due within the policy window. Any governed programme's work that waited is then merged by Mandate as normal.

### A repo joins

- The design gate accepts the repo; the platform engineer adds it to the meta repo's configuration and runs Launchpad; Mandate reads Launchpad's readiness result and takes the repo in, registering it with the context service and the verification workflow's branch rules. Its first feature wave waits for the platform contract.

## Engineering rules

Every component follows these; each has a check in the build or a test.

| Id | Rule | Why |
| --- | --- | --- |
| ER-01 | Every step and every write to Paperclip or GitHub carries an idempotency key derived from the work item and step, so a repeat has one effect | Nothing runs twice (REQ-91) |
| ER-02 | A state change and the action it causes leave in one transaction through the outbox; a sender delivers and retries; receivers are idempotent | Two stores (Mandate, Temporal) never disagree after a crash |
| ER-03 | Events are hints. Mandate reads current state from the source before acting on any event | Events are at least once and unordered |
| ER-04 | Mandate's code applies typed policy rules, schema checks and comparisons only. Any judgement is a role agent's call or a human's decision | Mandate never judges in its own name |
| ER-05 | Every step run and ledger entry carries the version stamp: contract, block versions, skills, rules, agent setup, policy revision, Mandate release | Measures and promotion compare like with like (REQ-78) |
| ER-06 | Content from outside the programme is marked at intake; the mark follows anything derived from it; marked content never sits where an agent reads instructions; briefs show it raw | Untrusted content never instructs (REQ-104) |
| ER-07 | Times are stored in UTC; every window is computed on the programme's calendar and time zone | REQ-110 |
| ER-08 | Secrets live only in Mandate's secret store; they never appear in artifacts, the ledger, logs or exports; no agent holds merge rights | Security attribute |
| ER-09 | When something is unknown or unverifiable (a Paperclip release, a contract block version, a signature), Mandate stops that work and escalates; it never falls back to a default | ADH accepted defaults and fallbacks |
| ER-10 | Every action records its actor; Mandate's own identity performs only mechanical steps the workflow or a recorded decision requires | REQ-40 |
| ER-11 | Personal data is redacted from evidence at intake, before hashing | REQ-107 |
| ER-12 | Packages talk only through their public interfaces; the import-boundary check fails the build otherwise | Claude Code can change one capability safely |

## Quality attributes

| Attribute (product PRD section 10) | Design that delivers it |
| --- | --- |
| Autonomous execution | The runner moves work between gates on events and the sweep (AD-2, AD-3); escalations go to an agent outside the dispute first |
| Integrity | State as rows plus short Temporal steps (AD-4); idempotency and outbox (ER-01, ER-02); read before act (ER-03) |
| Evidence integrity | Central signed verification workflow and signature checks (AD-7, CTR-06) |
| Auditability | Hash-chained ledger with daily signed checkpoints (AD-5); verifiable export |
| Authority | Signoffs only by the holder at its rung; Mandate posts the merge check only after the signoff is recorded in the ledger (AD-6, AD-8, ER-10) |
| Security | Nothing merges into develop or main without Mandate's check (AD-8); secret store (ER-08); untrusted content marked (ER-06); Paperclip's decision model off |
| Isolation | Programme scoping in every query and in the plugin's API (CTR-09) |
| Privacy | Redaction at intake (ER-11); 30-day evidence retention with hashes kept |
| Recovery within 1 hour | One Postgres and Temporal on Postgres, backed up with point-in-time restore; stateless processes restart; the sweep repairs gaps |
| Responsiveness within 1 minute | Events as triggers with a one-minute sweep behind them |
| Platform independence | API and plugin only; refuse unknown Paperclip releases (ER-09) |
| Buildability | Modular monolith with enforced boundaries (AD-12, ER-12); test strategy in section 9 |

## Test strategy

| Layer | What it proves | Runs |
| --- | --- | --- |
| Acceptance tests | Every requirement has at least one test tagged with its REQ id; the build fails if a requirement has none | Every change |
| Journey scenarios | Each of J-01 to J-29 runs end to end against real Paperclip (an ephemeral pinned instance per run) and real GitHub (sandbox repos, namespaced per run), with deterministic real agents; no fakes (PL-5) | Every change |
| Sandbox end to end | After the last wave of INIT-MANDATE-001 (the sandbox fix stage), every journey runs against real Paperclip, real GitHub and real agents on `mandate-sandbox`, a small throwaway programme (a meta repo plus one or two toy repos) created through Launchpad. Failures are fixed in Mandate until every journey passes; the phase 0 checks run here before any code | Phase 0, the sandbox fix stage, then nightly |
| Contract tests | Each seam (CTR-01 to 11) live against the pinned Paperclip release and the sandbox's GitHub repos; no recordings | Every change and nightly |
| Fault injection | Processes killed mid-step; events duplicated, reordered and dropped; webhooks lost; Paperclip or GitHub unreachable. Nothing lost, repeated or skipped; no gate decided while a platform is down | Every change |
| Property tests | Ledger chain verifies and detects any edit or deletion; idempotency holds for every step | Every change |
| Autonomy simulation | Synthetic decision streams, including anchored agreement, critical misses, unexercised changes and emergency merges, show that gates promote and demote exactly as policy says | Every change to `autonomy` or `policy` |
| Security tests | Hostile issue text (J-29); forged or unsigned evidence; a changed test set; attempts to merge without the check, or with a check on an old head; a signoff by someone who does not hold the gate; attempts to decide through an app identity | Every change |
| ADH regressions | Each of the twelve ADH review findings as a named test | Every change |
| Upgrade tests | Work pinned to an older contract and block versions keeps running correctly across a new Mandate release (REQ-114) | Every release |
| Drills | Point-in-time restore with in-flight work (REQ-115); emergency merge on Mandate's own repo (REQ-109) | Quarterly |
| Conduit acceptance run | Once Mandate is complete, Conduit is onboarded and delivered by Mandate; every issue found is fixed in Mandate and the run continues | Once, after the sandbox fix stage |
