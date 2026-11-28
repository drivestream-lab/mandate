"""Live verify: the walking skeleton, end to end, on the real sandbox repositories.

    python tests/verify/verify_walking_skeleton.py

Run from the repository root with MANDATE_JOURNEY_AUTHOR_TOKEN set (mandate-builder opens the
pull requests, as in tests/journeys/README.md) and without KD's GitHub token. It brings up the
journey stack (pinned Paperclip, Postgres, Temporal), files a work item in Paperclip, runs the
walking-skeleton workflow on a Temporal worker, and then checks, from GitHub and the ledger:

1. mandate-sandbox-meta: a toy PRD pull request is checked before any signoff (failure), signed
   by the deciding role's recorded decision with Mandate's App applying the signoff, and merged
   at the signed head; the deciding role's call was sealed before the brief and appears nowhere
   on the pull request.
2. mandate-sandbox-svc: a toy wave is verified with run-signed evidence whose expectations were
   fixed by the signed PRD, signed the same way and merged at the verified head.
3. an App's Approve at an L0 gate is refused.
4. every step is in the ledger, the chain verifies, the wave's decision records the trusted
   mandate-verify commit, and each merge commit has the signed head as a parent.

Prints PASS and exits 0 only when every check holds.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import base64  # noqa: E402
import secrets  # noqa: E402
import uuid  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from temporalio.client import Client  # noqa: E402
from temporalio.contrib.pydantic import pydantic_data_converter  # noqa: E402

from src.business_services.gates.gate_decision_check_service import (  # noqa: E402
    GateDecisionCheckService,
)
from src.business_services.gates.gate_opening_service import GateOpeningService  # noqa: E402
from src.business_services.gates.sealed_call_service import SealedCallService  # noqa: E402
from src.business_services.gates.signoff_service import SignoffService  # noqa: E402
from src.business_services.gates.signoff_voiding_service import (  # noqa: E402
    SignoffVoidingService,
)
from src.business_services.ledger.ledger_append_service import LedgerAppendService  # noqa: E402
from src.business_services.release.evidence_verification_service import (  # noqa: E402
    EvidenceVerificationService,
)
from src.business_services.release.merge_service import MergeService  # noqa: E402
from src.business_services.release.unguarded_merge_sweep_service import (  # noqa: E402
    CHECKPOINT_ROLE,
    SEED_ROLE,
    UnguardedMergeSweepService,
)
from src.business_services.runner.walking_skeleton_runner_service import (  # noqa: E402
    VERIFIER_COMMIT_EVIDENCE,
    PRD_GATE_LABEL,
    WAVE_GATE_LABEL,
    SkeletonError,
    SkeletonWiring,
    WalkingSkeletonRunnerService,
)
from src.database.postgres.repository.gates.gate_repository import GateRepository  # noqa: E402
from src.database.postgres.repository.ledger.ledger_repository import (  # noqa: E402
    LedgerRepository,
)
from src.di.dependency_container import (  # noqa: E402
    configure_container,
    get_container,
    reset_container,
)
from src.engine.gates.merge_rules import merge_decision_role  # noqa: E402
from src.infra_services.attestation_service import AttestationService  # noqa: E402
from src.infra_services.github_app_service import GitHubAppService  # noqa: E402
from src.infra_services.paperclip_service import PaperclipService  # noqa: E402
from src.infra_services.postgres_service import PostgresService  # noqa: E402
from src.models.gate_models import PullRequestRef, RoleBrief  # noqa: E402
from src.models.ledger_models import (  # noqa: E402
    DecisionRecord,
    LedgerEntryType,
    RungType,
    SealedCallRecord,
    StoredLedgerEntry,
)
from src.models.signoff_models import GateDecisionStateType, GateRule  # noqa: E402
from src.models.workflow_activity_models import (  # noqa: E402
    SkeletonStageType,
    SkeletonWorkItem,
    WalkingSkeletonInput,
    WalkingSkeletonResult,
)
from src.engine.workflows.walking_skeleton_workflow import WalkingSkeletonWorkflow  # noqa: E402
from src.worker_main import build_worker  # noqa: E402
from tests.journeys.conftest import (  # noqa: E402,F401
    journey_stack,
    run_namespace,
    sandbox_github,
    test_app_credentials,
)
from tests.journeys.decide_blind_first.test_call_sealed_before_the_holder_sees_the_decision import (  # noqa: E402,E501
    app_postgres,
    throwaway_database,
)
from tests.journeys.journey_support import (  # noqa: E402
    SANDBOX_REPOS,
    RunNamespace,
    SandboxGitHub,
    StackAddresses,
)
from tests.journeys.release_a_wave.conftest import (  # noqa: E402,F401
    WaveBuilder,
    attestations,
    author_token,
    evidence_service,
    evidence_settings,
    signed_off_commit,
    signed_off_digest,
    wave_builder,
)
from tests.journeys.release_a_wave.support import (  # noqa: E402
    OWNER,
    SandboxPull,
    client,
    commit_parents,
    live_baseline,
    open_pull,
    pull_state,
)
from tests.journeys.sign_a_gate.conftest import github_app, mandate_token  # noqa: E402,F401
from tests.journeys.sign_a_gate.support import STAMP  # noqa: E402
from tests.contract.paperclip.paperclip_stack import MandateIdentity  # noqa: E402
from tests.journeys.test_agents.conftest import (  # noqa: E402,F401
    AgentDesk,
    agent_host,
    desk,
    mandate_identity,
    paperclip,
)

__all__ = [
    "agent_host",
    "app_postgres",
    "attestations",
    "author_token",
    "desk",
    "evidence_service",
    "evidence_settings",
    "github_app",
    "journey_stack",
    "mandate_identity",
    "mandate_token",
    "paperclip",
    "run_namespace",
    "sandbox_github",
    "signed_off_commit",
    "signed_off_digest",
    "test_app_credentials",
    "throwaway_database",
    "wave_builder",
]

META = SANDBOX_REPOS[1]
SVC = SANDBOX_REPOS[0]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "walking_skeleton"
DECIDING_ROLE = "mandate-challenger"
TASK_QUEUE_PREFIX = "walking-skeleton"
_WORKFLOW_SECONDS = 1800


class _DecidingRole:
    """The scripted deciding role on the test Paperclip, citing a note that must never reach a pull request."""

    def __init__(self, desk_: AgentDesk, note: str) -> None:
        self._desk = desk_
        self._note = note
        self._agent = desk_.hire("Deciding role", "deciding_role.py")
        self.asked = 0

    async def request_call(self, brief: RoleBrief) -> str | None:
        self.asked += 1
        body: dict[str, object] = {
            "options": [option.option_id for option in brief.options],
            "evidence": [self._note],
        }
        issue = self._desk.assign(self._agent, f"Decide {self.asked}", body)
        return self._desk.first_finished_run(self._agent, issue).stdout or None


def _patch_files(text: str, run: str) -> dict[str, str]:
    """The files a patch of new files creates: path to content (only whole-file additions)."""
    files: dict[str, str] = {}
    path: str | None = None
    lines: list[str] = []
    for line in text.replace("__RUN__", run).splitlines():
        if line.startswith("+++ b/"):
            path = line.removeprefix("+++ b/")
            lines = []
        elif path is not None and line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
            files[path] = "\n".join(lines) + "\n"
    return files


def _commit(repo: str, token: str, branch: str, path: str, text: str) -> str:
    with client(repo, token) as http:
        reply = http.put(
            f"/contents/{path}",
            json={
                "message": f"walking skeleton: {path}",
                "content": base64.b64encode(text.encode()).decode(),
                "branch": branch,
            },
        )
        reply.raise_for_status()
        return str(reply.json()["commit"]["sha"])


def _statuses(repo: str, token: str, sha: str) -> list[tuple[str, str, datetime]]:
    """Every mandate/gate-decision posted on a commit, newest first: state, description, time."""
    with client(repo, token) as http:
        reply = http.get(f"/commits/{sha}/statuses", params={"per_page": 100}).raise_for_status()
    return [
        (str(s["state"]), str(s.get("description") or ""), datetime.fromisoformat(s["created_at"]))
        for s in reply.json()
        if s["context"] == "mandate/gate-decision"
    ]


def _everything_on(repo: str, token: str, number: int, shas: tuple[str, ...]) -> str:
    """Everything visible on a pull request: body, comments, reviews, review comments, labels,
    the statuses of the given commits and the merge commit messages."""
    parts: list[str] = []
    with client(repo, token) as http:
        parts.append(str(http.get(f"/pulls/{number}").raise_for_status().json().get("body") or ""))
        for path in (f"/issues/{number}/comments", f"/pulls/{number}/reviews",
                     f"/pulls/{number}/comments"):  # fmt: skip
            listing = http.get(path, params={"per_page": 100}).raise_for_status().json()
            parts += [str(item.get("body") or "") for item in listing]
        issue = http.get(f"/issues/{number}").raise_for_status().json()
        parts += [str(label["name"]) for label in issue["labels"]]
        for sha in shas:
            parts.append(
                str(http.get(f"/commits/{sha}").raise_for_status().json()["commit"]["message"])
            )
    parts += [description for sha in shas for _, description, _ in _statuses(repo, token, sha)]
    return "\n".join(parts)


def _board_edits_description(identity: MandateIdentity, issue_id: str, text: str) -> None:
    """A board user edits an issue's description in Paperclip."""
    with httpx.Client(
        base_url=identity.base_url, headers={"Origin": identity.base_url}, timeout=60
    ) as board:
        board.post(
            "/api/auth/sign-in/email",
            json={"email": identity.board_email, "password": identity.board_password},
        ).raise_for_status()
        board.patch(f"/api/issues/{issue_id}", json={"description": text}).raise_for_status()


async def _entries(postgres: PostgresService) -> list[StoredLedgerEntry]:
    async with postgres.get_session() as session:
        return await LedgerRepository().read_all(session)


def _decisions(entries: list[StoredLedgerEntry], actor: str, role: str) -> list[StoredLedgerEntry]:
    return [
        e
        for e in entries
        if e.entry_type == LedgerEntryType.DECISION
        and e.payload.get("actor") == actor
        and e.payload.get("role") == role
    ]


@pytest.fixture
async def runner(
    postgres: PostgresService,
    github_app: GitHubAppService,
    paperclip: PaperclipService,
    attestations: AttestationService,
    evidence_service: EvidenceVerificationService,
    desk: AgentDesk,
) -> AsyncIterator[WalkingSkeletonRunnerService]:
    """The runner wired over real services, bound in the container the worker resolves from."""
    note = f"skeleton-note-{secrets.token_hex(6)}"
    ledger = LedgerAppendService(postgres, LedgerRepository())
    sealed = SealedCallService(postgres, ledger, LedgerRepository())
    checks = GateDecisionCheckService(SignoffService(ledger), SignoffVoidingService(ledger))
    service = WalkingSkeletonRunnerService(
        paperclip,
        github_app,
        postgres,
        ledger,
        LedgerRepository(),
        sealed,
        GateOpeningService(postgres, GateRepository(), sealed),
        checks,
        MergeService(checks, ledger),
        UnguardedMergeSweepService(ledger),
        evidence_service,
        attestations,
        SkeletonWiring(roles=_DecidingRole(desk, note), stamp=STAMP, owner=OWNER),
    )
    reset_container()
    configure_container()
    get_container().binder.bind(WalkingSkeletonRunnerService, to=service)
    try:
        yield service
    finally:
        reset_container()


@pytest.mark.req("REQ-01")
@pytest.mark.req("REQ-02")
@pytest.mark.req("REQ-39")
@pytest.mark.req("REQ-40")
@pytest.mark.req("REQ-42")
@pytest.mark.req("REQ-43")
@pytest.mark.req("REQ-54")
@pytest.mark.req("REQ-55")
@pytest.mark.req("REQ-60")
@pytest.mark.req("REQ-61")
@pytest.mark.req("REQ-62")
@pytest.mark.req("REQ-63")
@pytest.mark.req("REQ-86")
@pytest.mark.req("REQ-103")
@pytest.mark.req("REQ-108")
@pytest.mark.req("REQ-118")
@pytest.mark.req("REQ-121")
@pytest.mark.req("REQ-122")
async def test_a_toy_prd_and_a_toy_wave_are_signed_verified_and_merged_end_to_end(
    runner: WalkingSkeletonRunnerService,
    mandate_identity: MandateIdentity,
    postgres: PostgresService,
    github_app: GitHubAppService,
    journey_stack: StackAddresses,
    run_namespace: RunNamespace,
    sandbox_github: SandboxGitHub,
    wave_builder: WaveBuilder,
    attestations: AttestationService,
    signed_off_digest: str,
    author_token: str,
    mandate_token: str,
) -> None:
    run = run_namespace.run_id
    prd_path = f"prd/toy-prd-{run}.md"
    caller_path = f".github/workflows/walking-skeleton-{run}.yml"
    prd_text = (
        (FIXTURES / "toy_prd.md")
        .read_text(encoding="utf-8")
        .replace("__CALLER_WORKFLOW__", caller_path)
        .replace("__TEST_SET_DIGEST__", signed_off_digest)
        .replace("__RUN__", run)
    )

    # The toy PRD on the meta repository, and a second pull request for the L0 refusal.
    prd_branch = sandbox_github.create_branch(META, "toy-prd")
    _commit(META, author_token, prd_branch, prd_path, prd_text)
    refusal_branch = sandbox_github.create_branch(META, "toy-prd-l0")
    _commit(META, author_token, refusal_branch, prd_path, prd_text)
    prd = open_pull(META, prd_branch, author_token, "", mandate_token, f"[{run}] toy PRD", True)
    refusal = open_pull(
        META, refusal_branch, author_token, "", mandate_token, f"[{run}] L0 refusal", True
    )

    # The toy wave on the service repository: a caller that runs on push, then the patch.
    name = f"walking-skeleton-{run}"
    built = wave_builder.wave_branch(name)
    assert built.workflow == caller_path
    changed = _patch_files((FIXTURES / "toy_change.patch").read_text(encoding="utf-8"), run)
    head = built.head
    for path, text in changed.items():
        head = wave_builder.push_file(built.branch, path, text)
    assert wave_builder.wait_for_run(head) == "success"
    wave_branch = built.branch
    wave = open_pull(SVC, wave_branch, author_token, "", mandate_token, f"[{run}] toy wave", True)

    item = SkeletonWorkItem(
        work_item_id=uuid.uuid4(),
        initiative="INIT-SKELETON",
        deciding_role=DECIDING_ROLE,
        prd_pull=prd.ref,
        prd_path=prd_path,
        wave_paths=(f"{name}.txt", *changed, caller_path),
        wave_pull=wave.ref,
        refusal_pull=refusal.ref,
        sweep_repos=(META, SVC),
        baselines=(await live_baseline(github_app, META), await live_baseline(github_app, SVC)),
    )
    signer_head_before = await attestations.signer_head()
    moved_branch = sandbox_github.create_branch(META, "toy-prd-moved")
    _commit(META, author_token, moved_branch, prd_path, prd_text)
    moved = open_pull(META, moved_branch, author_token, "", mandate_token, f"[{run}] moved", True)
    try:
        # An edited work item stops the next step.
        edited = await runner.file_work_item(item.model_copy(update={"work_item_id": uuid.uuid4()}))
        _board_edits_description(mandate_identity, edited, "{}")
        with pytest.raises(SkeletonError, match="work item was edited"):
            await runner.sweep_governed_branches(edited)

        # A push between open and settle: the role called on another head, so nothing is signed.
        moved_issue = await runner.file_work_item(
            item.model_copy(update={"work_item_id": uuid.uuid4(), "prd_pull": moved.ref})
        )
        opened = await runner.open_gate(moved_issue, SkeletonStageType.PRD)
        pushed = moved.author_pushes("after-the-call")
        refused = await runner.settle_gate(moved_issue, SkeletonStageType.PRD, opened.gate_id, None)
        assert refused.state == "head_moved" and refused.head_sha == pushed, refused
        assert pull_state(META, mandate_token, moved.ref.number) == "open"
        reviews = _everything_on(META, mandate_token, moved.ref.number, (pushed,))
        assert "approve" not in reviews.lower() and PRD_GATE_LABEL not in reviews
        assert not _decisions(
            await _entries(postgres), DECIDING_ROLE, _role(PRD_GATE_LABEL, moved.ref)
        )
        moved.close()

        client_ = await Client.connect(
            journey_stack.temporal_address, data_converter=pydantic_data_converter
        )
        queue = f"{TASK_QUEUE_PREFIX}-{run}"
        async with build_worker(client_, queue):
            result: WalkingSkeletonResult = await client_.execute_workflow(
                WalkingSkeletonWorkflow.run,
                WalkingSkeletonInput(work_item=item),
                id=f"walking-skeleton-{run}",
                task_queue=queue,
                execution_timeout=timedelta(seconds=_WORKFLOW_SECONDS),
            )
        await _check_everything(
            result,
            postgres,
            attestations,
            mandate_token,
            signer_head_before,
            await github_app.app_login(),
            prd,
            wave,
            refusal,
        )
    finally:
        for pull in (prd, refusal, wave, moved):
            pull.close()


def _role(label: str, ref: PullRequestRef) -> str:
    rule = GateRule(
        label=label,
        branch="develop",
        rung=RungType.L2,
        holders=frozenset({"unused"}),
        deciding_role=DECIDING_ROLE,
    )
    return merge_decision_role(rule, ref)


def _brief_posted_at(repo: str, token: str, number: int) -> datetime:
    with client(repo, token) as http:
        comments = http.get(f"/issues/{number}/comments").raise_for_status().json()
    return min(datetime.fromisoformat(str(c["created_at"])) for c in comments)


async def _check_everything(
    result: WalkingSkeletonResult,
    postgres: PostgresService,
    attestations: AttestationService,
    mandate_token: str,
    signer_head_before: str,
    app_login: str,
    prd: SandboxPull,
    wave: SandboxPull,
    refusal: SandboxPull,
) -> None:
    pulls = {
        SkeletonStageType.PRD: (prd, PRD_GATE_LABEL),
        SkeletonStageType.WAVE: (wave, WAVE_GATE_LABEL),
    }
    entries = await _entries(postgres)
    sealed = {str(e.payload["gate_id"]): e for e in entries if e.entry_type == "sealed_call"}
    reveals = {str(e.payload["gate_id"]): e for e in entries if e.entry_type == "call_reveal"}
    assert {str(r.gate_id) for r in result.stages} <= set(sealed) & set(reveals)

    for summary in result.stages:
        pull, label = pulls[summary.stage]
        settled = summary.settled
        # The check failed before the signoff; it passed, and the merge came, only after it.
        assert summary.before_signoff.state is GateDecisionStateType.FAILURE, summary
        assert settled.state == "merged", settled.reason
        signed_head = settled.head_sha or ""
        assert pull_state(pull.repo, mandate_token, pull.ref.number) == "merged"
        assert signed_head in commit_parents(pull.repo, mandate_token, settled.merge_commit or "")
        # Read back from GitHub: a failure was posted on the signed head, then a success.
        posted_states = _statuses(pull.repo, mandate_token, signed_head)
        assert posted_states[0][0] == "success"
        failed_before = [t for state, _, t in posted_states if state == "failure"]
        assert failed_before and min(failed_before) <= posted_states[0][2]
        # The ledger: sealed, then the deciding role's decision on that head, then the reveal.
        gate = str(summary.gate_id)
        decision = _decisions(entries, DECIDING_ROLE, _role(label, pull.ref))
        assert len(decision) == 1 and decision[0].payload["target_version"] == signed_head
        assert decision[0].payload["choice"] == "approve"
        assert sealed[gate].sequence < decision[0].sequence < reveals[gate].sequence
        assert len(_decisions(entries, app_login, label)) == 1

    # Blind first: sealed before the brief was posted, and nowhere on the PRD pull request.
    prd_gate = str(next(s.gate_id for s in result.stages if s.stage is SkeletonStageType.PRD))
    record = SealedCallRecord.model_validate(sealed[prd_gate].payload)
    assert record.call is not None and record.nonce is not None
    prd_settled = next(s for s in result.stages if s.stage is SkeletonStageType.PRD).settled
    visible = _everything_on(
        prd.repo,
        mandate_token,
        prd.ref.number,
        (prd_settled.head_sha or "", prd_settled.merge_commit or ""),
    )
    for secret in (*record.call.reasons, *record.call.evidence_cited, record.nonce):
        assert secret not in visible
    posted = _brief_posted_at(prd.repo, mandate_token, prd.ref.number)
    # GitHub stamps whole seconds, so the comparison is at that grain.
    assert sealed[prd_gate].recorded_at.replace(microsecond=0) <= posted

    # The wave's decision records the trusted mandate-verify commit, which is main's head now.
    wave_decision = DecisionRecord.model_validate(
        _decisions(entries, DECIDING_ROLE, _role(WAVE_GATE_LABEL, wave.ref))[0].payload
    )
    trusted = {e.kind: e.reference for e in wave_decision.evidence}[VERIFIER_COMMIT_EVIDENCE]
    wave_summary = next(s for s in result.stages if s.stage is SkeletonStageType.WAVE)
    assert trusted == wave_summary.settled.evidence_commit == await attestations.signer_head()
    assert trusted == signer_head_before

    # Every step is in the ledger: the seeds and checkpoints of both repositories' branches.
    roles = [str(e.payload.get("role")) for e in entries if e.entry_type == "decision"]
    assert roles.count(SEED_ROLE) == 4 and roles.count(CHECKPOINT_ROLE) >= 4
    assert len(result.seed.seeded) == 4

    # The L0 gate refuses an App's Approve.
    refused_at_l0 = [
        d for state, d, _ in _statuses(refusal.repo, mandate_token, refusal.head_sha())
        if state == "failure" and "decided by a person" in d
    ]  # fmt: skip
    assert refused_at_l0, "no L0 refusal on the pull request's statuses"
    assert result.l0_refusal.state is GateDecisionStateType.FAILURE

    # The polling steps ran, found nothing to answer, and the chain verifies.
    assert len(result.rechecks) == 3 and len(result.sweeps) == 3
    assert all(not report.escalations for report in result.rechecks)
    assert all(not report.findings and not report.reverts for report in result.sweeps)
    chain = await LedgerAppendService(postgres, LedgerRepository()).verify()
    assert chain.is_intact, chain.problems


if __name__ == "__main__":
    code = pytest.main([__file__, "-x", "-q", "-p", "no:cacheprovider"])
    print("PASS" if code == 0 else "FAIL")
    sys.exit(int(code))
