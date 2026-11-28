"""The steps of the walking skeleton: a toy PRD and a toy wave signed, verified and merged.

The work item is filed in Paperclip and read back from there for every step. For each of the two
gates (the PRD pull request on the meta repository, then the wave pull request on the service
repository) the steps are: open the gate (the deciding role's call is sealed in the ledger before
the brief is posted, and a call never goes on the pull request at an intent gate), check it
before any signoff (it must fail), record the deciding role's decision from its sealed call and
let Mandate's App apply the signoff and merge at the head the check passed on, then reveal the
call. The gates run at L2: the deciding role signs, Mandate's App applies. An L0 gate needs a
person, so a separate step shows that an App's Approve is refused there.

What the wave's evidence must match (the repository, caller workflow, test set, quarantine,
plugins and test-set digest) is read from the PRD the deciding role signed: the file at the
head of its recorded attestation, whose digest is the attested one. It is never read from the
commit under test. The decision entry of a wave records the mandate-verify commit the evidence
was trusted under.

Mandate decides nothing here: the choice recorded is the option in the deciding role's call, and
the rules that pass or fail a gate are the existing pure ones.
"""

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import yaml
from injector import NoInject, inject
from pydantic import ValidationError

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.gate_decision_check_service import (
    GateDecisionCheckService,
    WaveEvidence,
)
from src.business_services.gates.gate_opening_service import GateOpeningService
from src.business_services.gates.sealed_call_service import (
    DecidingRoleCallSource,
    SealedCallService,
)
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.business_services.release.merge_service import MergeService, MergeStateType
from src.business_services.release.unguarded_merge_sweep_service import (
    CheckpointExistsError,
    UnguardedMergeSweepService,
)
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.engine.gates.merge_rules import (
    APPROVE_CHOICE,
    REQUEST_CHANGES_CHOICE,
    attestation_body,
    decided_attestation,
    merge_decision_record,
    merge_decision_role,
)
from src.engine.gates.non_merge_rules import decision_role
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.attestation_service import AttestationService
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.paperclip_service import PaperclipService
from src.infra_services.postgres_service import PostgresService
from src.models.evidence_models import EvidenceRefusal, EvidenceTarget, VerifiedEvidence
from src.models.evidence_models import WaveEvidenceSpec
from src.models.gate_models import (
    BriefOption,
    GateBrief,
    GateClassType,
    PullRequestRef,
)
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import EvidenceReference, LedgerEntryType, RungType, SealedCallRecord
from src.models.paperclip_models import NewIssue
from src.models.role_output_models import DecidingRoleCall
from src.models.signoff_models import (
    ArtifactLink,
    Attestation,
    AttestedUpstream,
    DecisionLink,
    GateRule,
)
from src.models.sweep_models import SweepConfig
from src.models.workflow_activity_models import (
    CheckedGate,
    GateOpened,
    GateSettled,
    L0Refusal,
    RecheckResult,
    SeedReport,
    SkeletonStageType,
    SkeletonWorkItem,
    SweepResult,
)
from src.models.signoff_models import GOVERNED_BRANCHES

PRD_GATE_LABEL = "spec-lgtm"
WAVE_GATE_LABEL = "wave-accepted"
VERIFIER_COMMIT_EVIDENCE = "mandate-verify-commit"
EVIDENCE_RUN_EVIDENCE = "evidence-run"
EVIDENCE_BLOCK = re.compile(r"```wave-evidence\n(?P<body>.*?)\n```", re.DOTALL)
_EVIDENCE_ATTEMPTS = 3
_MOVED_SIGNER = "is now"
_STEP_WORKFLOW = "walking-skeleton/1"


@dataclass(frozen=True)
class SkeletonWiring:
    """What the skeleton is told besides its services: who the deciding role is asked through,
    the version stamp on every entry, and the owner of the repositories."""

    roles: DecidingRoleCallSource
    stamp: VersionStamp
    owner: str


class SkeletonError(BaseAppException):
    """A step cannot go on; the reason says why."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="WALKING_SKELETON_STOPPED", message=detail, status_code=409)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _RecordingChecker:
    """Verifies evidence through the service and remembers what it accepted."""

    def __init__(self, service: EvidenceVerificationService) -> None:
        self._service = service
        self.accepted: VerifiedEvidence | None = None

    async def verify(self, target: EvidenceTarget) -> VerifiedEvidence:
        self.accepted = await self._service.verify(target)
        return self.accepted


class WalkingSkeletonRunnerService(BaseBusinessService):
    """Runs the skeleton's steps against real services."""

    @inject
    def __init__(
        self,
        paperclip: PaperclipService,
        github: GitHubAppService,
        postgres: PostgresService,
        ledger: LedgerAppendService,
        ledger_repository: LedgerRepository,
        sealed_calls: SealedCallService,
        opening: GateOpeningService,
        checks: GateDecisionCheckService,
        merges: MergeService,
        sweeps: UnguardedMergeSweepService,
        evidence: EvidenceVerificationService,
        attestations: AttestationService,
        wiring: NoInject[SkeletonWiring],
    ) -> None:
        super().__init__()
        self._paperclip = paperclip
        self._github = github
        self._postgres = postgres
        self._ledger = ledger
        self._ledger_repository = ledger_repository
        self._sealed_calls = sealed_calls
        self._opening = opening
        self._checks = checks
        self._merges = merges
        self._sweeps = sweeps
        self._evidence = evidence
        self._attestations = attestations
        self._wiring = wiring

    # The work item lives in Paperclip.

    async def file_work_item(self, item: SkeletonWorkItem) -> str:
        """File the work item as a Paperclip issue (its description is the item) and return the id."""
        step = "file-work-item"
        run = await self._paperclip.open_run(str(item.work_item_id), step)
        issue = await self._paperclip.create_issue(
            run,
            str(item.work_item_id),
            step,
            NewIssue(
                title=f"{item.initiative}: toy PRD and toy wave",
                description=item.model_dump_json(),
            ),
        )
        return issue.id

    async def _item(self, issue_id: str) -> SkeletonWorkItem:
        issue = await self._paperclip.get_issue(issue_id)
        try:
            return SkeletonWorkItem.model_validate_json(issue.description or "")
        except ValidationError as error:
            raise SkeletonError("the work item in Paperclip cannot be read") from error

    # Gates, links and evidence built from the work item.

    async def _rule(self, item: SkeletonWorkItem, stage: SkeletonStageType) -> GateRule:
        holder = await self._github.app_login()
        return GateRule(
            label=PRD_GATE_LABEL if stage is SkeletonStageType.PRD else WAVE_GATE_LABEL,
            branch="develop",
            rung=RungType.L2,
            holders=frozenset({holder}),
            wave=stage is SkeletonStageType.WAVE,
            deciding_role=item.deciding_role,
        )

    async def _rules(self, item: SkeletonWorkItem) -> tuple[GateRule, GateRule]:
        return (
            await self._rule(item, SkeletonStageType.PRD),
            await self._rule(item, SkeletonStageType.WAVE),
        )

    @staticmethod
    def _pull(item: SkeletonWorkItem, stage: SkeletonStageType) -> PullRequestRef:
        return item.prd_pull if stage is SkeletonStageType.PRD else item.wave_pull

    @staticmethod
    def _links(
        item: SkeletonWorkItem, prd_gate_id: UUID | None
    ) -> tuple[tuple[ArtifactLink, ...], tuple[DecisionLink, ...]]:
        """The PRD is upstream of the wave; its decision is held by the deciding role."""
        artifact = (ArtifactLink(upstream=item.prd_pull, downstream=item.wave_pull),)
        if prd_gate_id is None:
            return artifact, ()
        decision = DecisionLink(
            artifact=item.prd_pull,
            downstream=item.wave_pull,
            decision_role=decision_role(GateClassType.INTENT, prd_gate_id),
            holder=item.deciding_role,
        )
        return artifact, (decision,)

    async def _digests(
        self, owner_repo: str, commit: str, paths: Sequence[str]
    ) -> tuple[tuple[str, ...], dict[str, bytes]]:
        tree = await self._attestations.tree_blobs(owner_repo, commit)
        contents: dict[str, bytes] = {}
        for path in paths:
            if path not in tree:
                raise SkeletonError(f"{path} is not in {owner_repo} at {commit}")
            contents[path] = await self._attestations.blob(owner_repo, tree[path][1])
        return tuple(hashlib.sha256(contents[path]).hexdigest() for path in paths), contents

    async def _attestation(
        self,
        item: SkeletonWorkItem,
        stage: SkeletonStageType,
        rule: GateRule,
        head: str,
    ) -> Attestation:
        ref = self._pull(item, stage)
        paths = (item.prd_path,) if stage is SkeletonStageType.PRD else item.wave_paths
        digests, _ = await self._digests(f"{self._wiring.owner}/{ref.repo}", head, paths)
        upstream: tuple[AttestedUpstream, ...] = ()
        if stage is SkeletonStageType.WAVE:
            upstream = (
                AttestedUpstream(
                    repo=item.prd_pull.repo,
                    pull_request=item.prd_pull.number,
                    head=await self._github.read_head_sha(item.prd_pull),
                ),
            )
        return Attestation(
            initiative=item.initiative,
            head=head,
            gate=rule.label,
            repo=ref.repo,
            pull_request=ref.number,
            digests=digests,
            artifact_paths=paths,
            upstream=upstream,
        )

    async def _wave_spec(self, item: SkeletonWorkItem) -> WaveEvidenceSpec | None:
        """What the wave's evidence must match, from the PRD's recorded signoff; None when the
        deciding role has not signed the PRD."""
        prd_rule = await self._rule(item, SkeletonStageType.PRD)
        prd_head = await self._github.read_head_sha(item.prd_pull)
        record = await self._ledger.latest_decision_record(
            item.deciding_role, merge_decision_role(prd_rule, item.prd_pull), prd_head
        )
        if record is None:
            return None
        attestation = decided_attestation(record)
        if isinstance(attestation, str):
            raise SkeletonError(attestation)
        if attestation.artifact_paths != (item.prd_path,):
            raise SkeletonError("the PRD's attestation does not name the PRD file")
        owner_repo = f"{self._wiring.owner}/{item.prd_pull.repo}"
        digests, contents = await self._digests(
            owner_repo, attestation.head, attestation.artifact_paths
        )
        if digests != attestation.digests:
            raise SkeletonError("the PRD at the attested head is not what was attested")
        found = EVIDENCE_BLOCK.search(contents[item.prd_path].decode("utf-8"))
        if found is None:
            raise SkeletonError("the signed PRD names no wave evidence")
        try:
            return WaveEvidenceSpec.model_validate(yaml.safe_load(found.group("body")))
        except (ValidationError, yaml.YAMLError) as error:
            raise SkeletonError("the wave evidence in the signed PRD is not readable") from error

    async def _wave(
        self, item: SkeletonWorkItem, checker: _RecordingChecker | None = None
    ) -> WaveEvidence | None:
        spec = await self._wave_spec(item)
        if spec is None:
            return None
        recording = checker or _RecordingChecker(self._evidence)
        return WaveEvidence(recording, {WAVE_GATE_LABEL: spec}, self._wiring.owner)

    # Ledger reads.

    async def _sealed_call(self, gate_id: UUID) -> DecidingRoleCall | None:
        async with self._postgres.get_session() as session:
            entry = await self._ledger_repository.find_by_type_and_gate(
                session, LedgerEntryType.SEALED_CALL, gate_id
            )
        if entry is None:
            raise SkeletonError("no call was sealed for this gate")
        return SealedCallRecord.model_validate(entry.payload).call

    # Steps.

    async def seed_sweep_checkpoints(self, issue_id: str) -> SeedReport:
        """Seed each governed branch's checkpoint where none exists (once per fresh ledger)."""
        item = await self._item(issue_id)
        seeded: list[str] = []
        present: list[str] = []
        for repo in item.sweep_repos:
            for branch in sorted(GOVERNED_BRANCHES):
                try:
                    await self._sweeps.seed_checkpoint(
                        self._github, repo, branch, self._wiring.stamp
                    )
                    seeded.append(f"{repo}/{branch}")
                except CheckpointExistsError:
                    present.append(f"{repo}/{branch}")
        return SeedReport(seeded=tuple(seeded), already_present=tuple(present))

    async def open_gate(self, issue_id: str, stage: SkeletonStageType) -> GateOpened:
        """Seal the deciding role's call, then post the brief on the stage's pull request."""
        item = await self._item(issue_id)
        ref = self._pull(item, stage)
        head = await self._github.read_head_sha(ref)
        gate_class = (
            GateClassType.INTENT if stage is SkeletonStageType.PRD else GateClassType.VERIFICATION
        )
        brief = GateBrief(
            gate_class=gate_class,
            title=f"Sign the toy {stage.value}",
            what_is_decided=f"Whether {ref.repo}#{ref.number} is signed at this head",
            options=(
                BriefOption(
                    option_id=APPROVE_CHOICE, description="Sign this head", impact="It is merged"
                ),
                BriefOption(
                    option_id=REQUEST_CHANGES_CHOICE,
                    description="Do not sign this head",
                    impact="It is not merged",
                ),
            ),
            recommendation=APPROVE_CHOICE,
            recommendation_reason="The toy change follows the toy PRD",
            head_sha=head,
            evidence=(
                EvidenceReference(
                    kind="pull-request", reference=f"{ref.repo}#{ref.number}", digest=_sha256(head)
                ),
            ),
            after_signoff="The pull request is merged at this head",
        )
        opened = await self._opening.open_gate(
            item.work_item_id, brief, ref, self._wiring.roles, self._github, self._wiring.stamp
        )
        call = await self._sealed_call(opened.gate_id)
        shown = False
        if call is not None:
            shown = any(part in opened.brief_body for part in (*call.reasons, *call.evidence_cited))
        return GateOpened(
            gate_id=opened.gate_id,
            sealed_entry_hash=opened.sealed.sealed_entry_hash,
            call_on_pull_request=shown,
        )

    async def check_unsigned_gate(
        self, issue_id: str, stage: SkeletonStageType, prd_gate_id: UUID | None
    ) -> CheckedGate:
        """Run the check before any signoff exists; Mandate posts failure with its reason."""
        item = await self._item(issue_id)
        rule = await self._rule(item, stage)
        links, decision_links = self._links(item, prd_gate_id)
        outcome = await self._checks.evaluate_and_post(
            self._github,
            self._pull(item, stage),
            rule,
            self._wiring.stamp,
            await self._rules(item),
            links,
            decision_links,
            await self._wave(item) if stage is SkeletonStageType.WAVE else None,
        )
        return CheckedGate(state=outcome.state, head_sha=outcome.head_sha, reason=outcome.reason)

    async def settle_gate(
        self,
        issue_id: str,
        stage: SkeletonStageType,
        gate_id: UUID,
        prd_gate_id: UUID | None,
    ) -> GateSettled:
        """Record the deciding role's decision from its sealed call, then let Mandate's App apply
        the signoff and merge at the head the check passed on; reveal the call once merged."""
        item = await self._item(issue_id)
        ref = self._pull(item, stage)
        rule = await self._rule(item, stage)
        stamp = self._wiring.stamp
        call = await self._sealed_call(gate_id)
        if call is None:
            return _not_settled("the gate has no sealed call, so no decision is recorded")
        if call.option not in (APPROVE_CHOICE, REQUEST_CHANGES_CHOICE):
            raise SkeletonError(f"the sealed call picks {call.option}, which is not an option")
        head = await self._github.read_head_sha(ref)
        checker = _RecordingChecker(self._evidence)
        wave: WaveEvidence | None = None
        if stage is SkeletonStageType.WAVE:
            wave = await self._wave(item, checker)
            if wave is None:
                return _not_settled("the PRD has no recorded signoff, so no evidence spec exists")
            refusal = await self._verify_evidence(wave, rule, head, checker)
            if refusal is not None:
                return _not_settled(refusal, head)
        attestation = await self._attestation(item, stage, rule, head)
        record = merge_decision_record(rule, ref, attestation, call.option, datetime.now(UTC))
        accepted = checker.accepted
        if accepted is not None:
            extra = (
                _evidence(VERIFIER_COMMIT_EVIDENCE, accepted.signer_digest),
                _evidence(
                    EVIDENCE_RUN_EVIDENCE,
                    f"{accepted.repository}@{accepted.commit} "
                    f"run {accepted.run_id}.{accepted.run_attempt}",
                ),
            )
            record = record.model_copy(update={"evidence": record.evidence + extra})
        await self._ledger.record_decision_once(record, stamp, "the deciding role decided again")
        links, decision_links = self._links(item, prd_gate_id)
        rules = await self._rules(item)
        outcome = await self._merges.settle(
            self._github, ref, rule, stamp, rules, links, decision_links, wave
        )
        for _ in range(_EVIDENCE_ATTEMPTS - 1):
            moved = outcome.state is MergeStateType.CHECK_FAILED and _MOVED_SIGNER in outcome.reason
            if not moved:
                break
            outcome = await self._merges.settle(
                self._github, ref, rule, stamp, rules, links, decision_links, wave
            )
        if outcome.state is MergeStateType.MERGED:
            await self._sealed_calls.reveal(gate_id, True, stamp)
        return GateSettled(
            state=outcome.state.value,
            reason=outcome.reason,
            head_sha=None if outcome.check is None else outcome.check.head_sha,
            merge_commit=outcome.merge_commit,
            evidence_commit=None if accepted is None else accepted.signer_digest,
        )

    async def _verify_evidence(
        self, wave: WaveEvidence, rule: GateRule, head: str, checker: _RecordingChecker
    ) -> str | None:
        """Verify the head's evidence now, so the decision records the commit it was trusted
        under; a 'main is now' refusal means the evidence is run again, up to a few times."""
        spec = wave.specs[rule.label]
        reason = ""
        for _ in range(_EVIDENCE_ATTEMPTS):
            try:
                await checker.verify(spec.target_for(head))
                return None
            except EvidenceRefusal as refusal:
                reason = refusal.reason
                if _MOVED_SIGNER not in reason:
                    break
        return f"no run-signed evidence for this head: {reason}"

    async def refuse_app_at_l0(self, issue_id: str) -> L0Refusal:
        """Mandate's App applies the signoff on a pull request whose gate is at L0: the check
        refuses it, because an L0 gate is decided by a person."""
        item = await self._item(issue_id)
        ref = item.refusal_pull
        l0 = GateRule(
            label=PRD_GATE_LABEL,
            branch="develop",
            rung=RungType.L0,
            holders=frozenset({await self._github.app_login()}),
        )
        snapshot = await self._github.read_pull_request(ref)
        digests, _ = await self._digests(
            f"{self._wiring.owner}/{ref.repo}", snapshot.head_sha, (item.prd_path,)
        )
        attestation = Attestation(
            initiative=item.initiative,
            head=snapshot.head_sha,
            gate=l0.label,
            repo=ref.repo,
            pull_request=ref.number,
            digests=digests,
            artifact_paths=(item.prd_path,),
        )
        await self._github.add_label(ref, l0.label)
        await self._github.approve_pull(ref, snapshot.head_sha, attestation_body(attestation))
        if snapshot.is_draft:
            await self._github.mark_pull_ready(ref)
        outcome = await self._checks.evaluate_and_post(
            self._github, ref, l0, self._wiring.stamp, (l0,)
        )
        return L0Refusal(state=outcome.state, reason=outcome.reason)

    async def recheck_open_gates(self, issue_id: str, prd_gate_id: UUID | None) -> RecheckResult:
        """Re-evaluate every open pull request into a governed branch of the work item's repos."""
        item = await self._item(issue_id)
        links, decision_links = self._links(item, prd_gate_id)
        report = await self._checks.recheck_open_gates(
            self._github,
            item.sweep_repos,
            await self._rules(item),
            self._wiring.stamp,
            links,
            decision_links,
            await self._wave(item),
        )
        return RecheckResult(report=report)

    async def sweep_governed_branches(self, issue_id: str) -> SweepResult:
        """One sweep over the governed repositories against the baselines the work item carries."""
        item = await self._item(issue_id)
        config = SweepConfig(
            repos=item.sweep_repos,
            mandate_login=await self._github.app_login(),
            baselines=item.baselines,
        )
        return SweepResult(
            report=await self._sweeps.sweep(self._github, config, self._wiring.stamp)
        )


def _evidence(kind: str, reference: str) -> EvidenceReference:
    return EvidenceReference(kind=kind, reference=reference, digest=_sha256(reference))


def _not_settled(reason: str, head: str | None = None) -> GateSettled:
    return GateSettled(
        state=MergeStateType.NOT_SIGNED.value,
        reason=reason,
        head_sha=head,
        merge_commit=None,
        evidence_commit=None,
    )
