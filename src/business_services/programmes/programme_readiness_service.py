"""Shows whether a programme can start, and names each thing that stops it.

Four checks: every role has a usable agent; GitHub access works for every repo; the pinned
workflow loads (the meta repo's harness pin at the programme's commit names a skills repo and
release, and that release's workflow.yaml is read and parsed); and Mandate's own Paperclip agent
cannot create agents or skills or assign tasks. The agent's permission flags alone do not deny
the last two on the pinned Paperclip, so the interaction permissions are read and Paperclip itself is asked whether the agent may
take each skill action (its answer covers the skill-policy rules and the grants new agents get). Every check runs and each failure carries its cause.
"""

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.programmes.programme_from_meta_service import (
    RepositoryAccess,
    RepositoryAccessError,
)
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.paperclip_service import PaperclipError, PaperclipService
from src.models.paperclip_models import PaperclipAgent
from src.models.programme_models import (
    Programme,
    ReadinessCheckType,
    ReadinessFailure,
    ReadinessReport,
)

_USABLE_STATUSES = frozenset({"idle", "running", "active"})
_SKILL_ACTIONS = frozenset(
    {
        "skills.create",
        "skills.import",
        "skills.install",
        "skills.edit",
        "skills.update",
        "skills.test",
        "skills.reset",
        "skills.remove",
    }
)
_HARNESS_PIN_PATH = ".harness-pin.yaml"
_WORKFLOW_PATH = "workflow.yaml"


class _SkillsPin(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repo: str
    ref: str


class _WorkflowHeader(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract: str


class _HarnessPin(BaseModel):
    """The meta repo's .harness-pin.yaml: the delivery contract and the skills release it pins."""

    model_config = ConfigDict(extra="ignore")

    delivery_contract: str
    agent_skills: _SkillsPin


class ProgrammeNotReadyError(BaseAppException):
    """A programme was asked to start while a readiness check fails."""

    def __init__(self, report: ReadinessReport) -> None:
        causes = "; ".join(f"{f.check}: {f.subject}: {f.cause}" for f in report.failures)
        super().__init__(code="PROGRAMME_NOT_READY", message=causes, status_code=409)
        self.report = report


class ProgrammeReadinessService(BaseBusinessService):
    """Runs the readiness checks for a programme."""

    def __init__(self, paperclip: PaperclipService, repositories: RepositoryAccess) -> None:
        super().__init__()
        self._paperclip = paperclip
        self._repositories = repositories

    async def check(self, programme: Programme) -> ReadinessReport:
        """Run every check and return all failures, each with its cause."""
        failures = [
            *await self._role_agents(programme),
            *await self._repositories_reachable(programme),
            *await self._workflow_loads(programme),
            *await self._mandate_agent_limits(),
        ]
        return ReadinessReport(failures=tuple(failures))

    async def require_ready(self, programme: Programme) -> None:
        """Raise ProgrammeNotReadyError unless every check passes; any start goes through this."""
        report = await self.check(programme)
        if not report.ready:
            raise ProgrammeNotReadyError(report)

    async def _role_agents(self, programme: Programme) -> list[ReadinessFailure]:
        try:
            agents = {agent.name: agent for agent in await self._paperclip.list_agents()}
        except PaperclipError as error:
            return [
                _failure(ReadinessCheckType.ROLE_AGENT, "agents", f"cannot list agents: {error}")
            ]
        failures: list[ReadinessFailure] = []
        for role in programme.config.roles:
            agent = agents.get(role.agent)
            cause = (
                f"no agent named {role.agent} in the company"
                if agent is None
                else agent_unusable_cause(agent)
            )
            if cause:
                failures.append(_failure(ReadinessCheckType.ROLE_AGENT, role.name, cause))
        return failures

    async def _repositories_reachable(self, programme: Programme) -> list[ReadinessFailure]:
        failures: list[ReadinessFailure] = []
        for repo in programme.config.repos:
            try:
                await self._repositories.check_access(repo)
            except RepositoryAccessError as error:
                failures.append(_failure(ReadinessCheckType.REPOSITORY_ACCESS, repo, str(error)))
        return failures

    async def _workflow_loads(self, programme: Programme) -> list[ReadinessFailure]:
        pin = programme.config.workflow
        meta, ref = programme.config.meta_repo, programme.meta_commit
        try:
            harness = _HarnessPin.model_validate(
                yaml.safe_load(await self._repositories.read_file(meta, _HARNESS_PIN_PATH, ref))
            )
        except (RepositoryAccessError, yaml.YAMLError, ValidationError) as error:
            return [_failure(ReadinessCheckType.WORKFLOW, pin.contract, f"does not load: {error}")]
        skills = harness.agent_skills
        found = (harness.delivery_contract, skills.repo, skills.ref)
        if found != (pin.contract, pin.skills_repo, pin.version):
            cause = (
                f"the meta repo pins {found[0]} from {found[1]} at {found[2]}, "
                f"the programme pins {pin.contract} from {pin.skills_repo} at {pin.version}"
            )
            return [_failure(ReadinessCheckType.WORKFLOW, pin.contract, cause)]
        try:
            workflow = _WorkflowHeader.model_validate(
                yaml.safe_load(
                    await self._repositories.read_file(skills.repo, _WORKFLOW_PATH, skills.ref)
                )
            )
        except (RepositoryAccessError, yaml.YAMLError, ValidationError) as error:
            cause = f"{skills.repo}@{skills.ref} workflow does not load: {error}"
            return [_failure(ReadinessCheckType.WORKFLOW, pin.contract, cause)]
        if workflow.contract != pin.contract:
            cause = f"the workflow at {skills.ref} is for {workflow.contract}, not {pin.contract}"
            return [_failure(ReadinessCheckType.WORKFLOW, pin.contract, cause)]
        return []

    async def _mandate_agent_limits(self) -> list[ReadinessFailure]:
        agent_id = self._paperclip.agent_id
        subject = ReadinessCheckType.MANDATE_AGENT_LIMITS
        try:
            agent = await self._paperclip.get_agent(agent_id)
            interactions = (await self._paperclip.get_interaction_permissions(agent_id)).effective
        except PaperclipError as error:
            return [_failure(subject, agent_id, f"cannot read the agent's limits: {error}")]
        causes: list[str] = []
        if agent.permissions.can_create_agents:
            causes.append("it may create agents")
        if interactions.can_assign_tasks_to_agents:
            causes.append("it may assign tasks to agents")
        if interactions.can_configure_other_agents:
            causes.append("it may configure other agents")
        for action in sorted(_SKILL_ACTIONS):
            try:
                decision = await self._paperclip.evaluate_skill_action(action)
            except PaperclipError as error:
                causes.append(f"Paperclip could not say whether it may {action}: {error}")
                continue
            if decision.allowed:
                causes.append(f"Paperclip allows it {action} ({decision.reason})")
        return [_failure(subject, agent.name, cause) for cause in causes]


def agent_unusable_cause(agent: PaperclipAgent) -> str | None:
    if agent.lifecycle_state != "ready" or agent.status not in _USABLE_STATUSES:
        return f"agent {agent.name} is not usable: status {agent.status}, state {agent.lifecycle_state}"
    return None


def _failure(check: ReadinessCheckType, subject: str, cause: str) -> ReadinessFailure:
    return ReadinessFailure(check=check, subject=subject, cause=cause)
