"""Temporal worker entrypoint: the registry of business-service activities.

Each ActivityNameType value maps to the activity that serves it. An activity resolves its
business service from the container when it runs and passes the payload through; a unit test
keeps the enum and the registry in step. `build_worker` registers the workflows and wraps each
registered handler as a Temporal activity under its name.
"""

from collections.abc import Awaitable, Callable

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from src.business_services.runner.walking_skeleton_runner_service import (
    WalkingSkeletonRunnerService,
)
from src.di.dependency_container import provide_service
from src.engine.workflows.walking_skeleton_workflow import WalkingSkeletonWorkflow
from src.models.workflow_activity_models import (
    ActivityNameType,
    ActivityOutput,
    CheckedGate,
    FileWorkItemInput,
    GateOpened,
    GateSettled,
    L0Refusal,
    RecheckResult,
    SeedReport,
    SkeletonGateInput,
    SkeletonStageInput,
    SkeletonStepInput,
    SweepResult,
    WorkItemFiled,
)

ActivityHandler = Callable[..., Awaitable[ActivityOutput]]
"""An activity takes its own input model (one argument) and returns its own output model."""


def _runner() -> WalkingSkeletonRunnerService:
    return provide_service(WalkingSkeletonRunnerService)


async def file_work_item(payload: FileWorkItemInput) -> WorkItemFiled:
    return WorkItemFiled(issue_id=await _runner().file_work_item(payload.work_item))


async def seed_sweep_checkpoints(payload: SkeletonStepInput) -> SeedReport:
    return await _runner().seed_sweep_checkpoints(payload.issue_id)


async def open_gate(payload: SkeletonStageInput) -> GateOpened:
    return await _runner().open_gate(payload.issue_id, payload.stage)


async def check_unsigned_gate(payload: SkeletonStageInput) -> CheckedGate:
    return await _runner().check_unsigned_gate(payload.issue_id, payload.stage, payload.prd_gate_id)


async def settle_gate(payload: SkeletonGateInput) -> GateSettled:
    return await _runner().settle_gate(
        payload.issue_id, payload.stage, payload.gate_id, payload.prd_gate_id
    )


async def refuse_app_at_l0(payload: SkeletonStepInput) -> L0Refusal:
    return await _runner().refuse_app_at_l0(payload.issue_id)


async def recheck_open_gates(payload: SkeletonStepInput) -> RecheckResult:
    return await _runner().recheck_open_gates(payload.issue_id, payload.prd_gate_id)


async def sweep_governed_branches(payload: SkeletonStepInput) -> SweepResult:
    return await _runner().sweep_governed_branches(payload.issue_id)


ACTIVITY_REGISTRY: dict[ActivityNameType, ActivityHandler] = {
    ActivityNameType.FILE_WORK_ITEM: file_work_item,
    ActivityNameType.SEED_SWEEP_CHECKPOINTS: seed_sweep_checkpoints,
    ActivityNameType.OPEN_GATE: open_gate,
    ActivityNameType.CHECK_UNSIGNED_GATE: check_unsigned_gate,
    ActivityNameType.SETTLE_GATE: settle_gate,
    ActivityNameType.REFUSE_APP_AT_L0: refuse_app_at_l0,
    ActivityNameType.RECHECK_OPEN_GATES: recheck_open_gates,
    ActivityNameType.SWEEP_GOVERNED_BRANCHES: sweep_governed_branches,
}


def registered_activity_names() -> frozenset[ActivityNameType]:
    """Names the worker registers an activity for."""
    return frozenset(ACTIVITY_REGISTRY)


def build_worker(client: Client, task_queue: str) -> Worker:
    """A worker for the workflows and every registered activity, each under its own name."""
    return Worker(
        client,
        task_queue=task_queue,
        workflows=[WalkingSkeletonWorkflow],
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules("pydantic")
        ),
        activities=[
            activity.defn(name=name.value)(handler) for name, handler in ACTIVITY_REGISTRY.items()
        ],
    )
