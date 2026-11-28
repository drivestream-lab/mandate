"""The walking skeleton as a Temporal workflow: a toy PRD and a toy wave, signed, verified and
merged, with Mandate's polling steps scheduled between them.

The workflow only orders steps. Each step is a business-service activity called by name with a
typed payload; what a step decides is the rules' business, never this module's. After the work
item is filed and the sweep checkpoints are seeded, each gate is opened (the deciding role's
call is sealed first), checked before any signoff, settled (signoff applied, merge at the
verified head), and followed by a re-check of the open gates and one sweep of the governed
branches. The L0 refusal is shown last, and one more re-check and sweep close the run.
"""

from datetime import timedelta
from typing import TypeVar

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from pydantic import BaseModel

    from src.models.signoff_models import RecheckReport
    from src.models.sweep_models import SweepReport
    from src.models.workflow_activity_models import (
        ActivityNameType,
        CheckedGate,
        FileWorkItemInput,
        GateOpened,
        GateSettled,
        L0Refusal,
        RecheckResult,
        SeedReport,
        SkeletonGateInput,
        SkeletonStageInput,
        SkeletonStageType,
        SkeletonStepInput,
        StageSummary,
        SweepResult,
        WalkingSkeletonInput,
        WalkingSkeletonResult,
        WorkItemFiled,
    )

_Result = TypeVar("_Result", bound="BaseModel")
_STEP_TIMEOUT = timedelta(minutes=15)
_ONCE = RetryPolicy(maximum_attempts=1)
"""A step that writes to GitHub or the ledger runs once: a failure stops the run."""


async def _call(name: ActivityNameType, argument: BaseModel, result: type[_Result]) -> _Result:
    return await workflow.execute_activity(
        name.value,
        argument,
        result_type=result,
        start_to_close_timeout=_STEP_TIMEOUT,
        retry_policy=_ONCE,
    )


@workflow.defn
class WalkingSkeletonWorkflow:
    """Signs and merges the toy PRD, then the toy wave built on it."""

    @workflow.run
    async def run(self, start: WalkingSkeletonInput) -> WalkingSkeletonResult:
        filed = await _call(
            ActivityNameType.FILE_WORK_ITEM,
            FileWorkItemInput(work_item=start.work_item),
            WorkItemFiled,
        )
        issue = filed.issue_id
        seed = await _call(
            ActivityNameType.SEED_SWEEP_CHECKPOINTS, SkeletonStepInput(issue_id=issue), SeedReport
        )
        stages: list[StageSummary] = []
        rechecks: list[RecheckReport] = []
        sweeps: list[SweepReport] = []
        prd_gate: UUID | None = None
        for stage in (SkeletonStageType.PRD, SkeletonStageType.WAVE):
            opened = await _call(
                ActivityNameType.OPEN_GATE,
                SkeletonStageInput(issue_id=issue, stage=stage, prd_gate_id=prd_gate),
                GateOpened,
            )
            if stage is SkeletonStageType.PRD:
                prd_gate = opened.gate_id
            unsigned = await _call(
                ActivityNameType.CHECK_UNSIGNED_GATE,
                SkeletonStageInput(issue_id=issue, stage=stage, prd_gate_id=prd_gate),
                CheckedGate,
            )
            settled = await _call(
                ActivityNameType.SETTLE_GATE,
                SkeletonGateInput(
                    issue_id=issue, stage=stage, gate_id=opened.gate_id, prd_gate_id=prd_gate
                ),
                GateSettled,
            )
            stages.append(
                StageSummary(
                    stage=stage, gate_id=opened.gate_id, before_signoff=unsigned, settled=settled
                )
            )
            rechecks.append(await self._recheck(issue, prd_gate))
            sweeps.append(await self._sweep(issue))
        refusal = await _call(
            ActivityNameType.REFUSE_APP_AT_L0, SkeletonStepInput(issue_id=issue), L0Refusal
        )
        rechecks.append(await self._recheck(issue, prd_gate))
        sweeps.append(await self._sweep(issue))
        return WalkingSkeletonResult(
            issue_id=issue,
            seed=seed,
            stages=tuple(stages),
            l0_refusal=refusal,
            rechecks=tuple(rechecks),
            sweeps=tuple(sweeps),
        )

    async def _recheck(self, issue: str, prd_gate: UUID | None) -> RecheckReport:
        result = await _call(
            ActivityNameType.RECHECK_OPEN_GATES,
            SkeletonStepInput(issue_id=issue, prd_gate_id=prd_gate),
            RecheckResult,
        )
        return result.report

    async def _sweep(self, issue: str) -> SweepReport:
        result = await _call(
            ActivityNameType.SWEEP_GOVERNED_BRANCHES, SkeletonStepInput(issue_id=issue), SweepResult
        )
        return result.report
