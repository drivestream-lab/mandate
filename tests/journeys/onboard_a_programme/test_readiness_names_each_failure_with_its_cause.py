"""Journey: readiness shows each failure with its cause, and nothing starts while any fails."""

from pathlib import Path

import httpx
import pytest

from src.business_services.programmes.programme_from_meta_service import ProgrammeFromMetaService
from src.business_services.programmes.programme_readiness_service import (
    ProgrammeNotReadyError,
    ProgrammeReadinessService,
)
from src.infra_services.paperclip_service import PaperclipService
from src.models.programme_models import (
    Programme,
    ProgrammeConfig,
    ReadinessCheckType,
    RoleSetup,
    WorkflowPin,
)
from tests.contract.paperclip.conftest import settings_for
from tests.contract.paperclip.paperclip_stack import MandateIdentity
from tests.journeys.onboard_a_programme.conftest import META_REPO, GitHubRepositoryAccess

pytestmark = pytest.mark.req("REQ-02")


@pytest.fixture
async def programme(
    programme_from_meta: ProgrammeFromMetaService, meta_commit: str, role_agents: tuple[str, ...]
) -> Programme:
    return await programme_from_meta.create_programme(META_REPO, meta_commit)


def _broken(programme: Programme) -> Programme:
    config: ProgrammeConfig = programme.config.model_copy(
        update={
            "repos": (*programme.config.repos, "mandate-no-such-repo"),
            "roles": (*programme.config.roles, RoleSetup(name="verifier", agent="nobody")),
            "workflow": WorkflowPin(
                contract="sdd-delivery/v2",
                skills_repo="drivestream-lab/prayog-skills",
                version="v9.9.9",
            ),
        }
    )
    return programme.model_copy(update={"config": config})


async def test_a_ready_programme_has_no_failures_and_may_start(
    readiness: ProgrammeReadinessService, programme: Programme
) -> None:
    report = await readiness.check(programme)

    assert report.failures == ()
    await readiness.require_ready(programme)


async def test_each_failure_is_shown_with_its_cause_and_nothing_starts(
    readiness: ProgrammeReadinessService, programme: Programme
) -> None:
    broken = _broken(programme)

    report = await readiness.check(broken)

    by_check = {f.check: f for f in report.failures}
    assert set(by_check) == {
        ReadinessCheckType.ROLE_AGENT,
        ReadinessCheckType.REPOSITORY_ACCESS,
        ReadinessCheckType.WORKFLOW,
    }
    assert by_check[ReadinessCheckType.ROLE_AGENT].subject == "verifier"
    assert "no agent named nobody" in by_check[ReadinessCheckType.ROLE_AGENT].cause
    assert by_check[ReadinessCheckType.REPOSITORY_ACCESS].subject == "mandate-no-such-repo"
    assert "404" in by_check[ReadinessCheckType.REPOSITORY_ACCESS].cause
    assert (
        "at v0.5.6, the programme pins sdd-delivery/v2 from drivestream-lab/prayog-skills at v9.9.9"
        in by_check[ReadinessCheckType.WORKFLOW].cause
    )
    with pytest.raises(ProgrammeNotReadyError) as stopped:
        await readiness.require_ready(broken)
    assert stopped.value.report == report


async def test_a_pin_to_a_tag_that_does_not_exist_fails_with_its_cause(
    readiness: ProgrammeReadinessService,
    programme: Programme,
    meta_commit_pinning_a_missing_tag: str,
) -> None:
    pinned = programme.model_copy(update={"meta_commit": meta_commit_pinning_a_missing_tag})
    config = programme.config.model_copy(
        update={"workflow": programme.config.workflow.model_copy(update={"version": "v9.9.9"})}
    )

    report = await readiness.check(pinned.model_copy(update={"config": config}))

    assert [f.check for f in report.failures] == [ReadinessCheckType.WORKFLOW]
    assert "drivestream-lab/prayog-skills@v9.9.9 workflow does not load" in report.failures[0].cause
    assert "404" in report.failures[0].cause


@pytest.mark.req("REQ-40")
async def test_an_agent_that_can_create_agents_or_assign_tasks_fails_readiness(
    programme: Programme,
    mandate_identity: MandateIdentity,
    repository_access: GitHubRepositoryAccess,
) -> None:
    unrestricted = PaperclipService(
        settings_for(mandate_identity, agent_id=mandate_identity.other_agent_id)
    )
    await unrestricted.initialize()
    try:
        report = await ProgrammeReadinessService(unrestricted, repository_access).check(programme)
    finally:
        await unrestricted.close()

    assert {f.check for f in report.failures} == {ReadinessCheckType.MANDATE_AGENT_LIMITS}
    causes = " | ".join(f.cause for f in report.failures)
    for expected in ("create agents", "assign tasks to agents"):
        assert expected in causes


@pytest.mark.req("REQ-40")
async def test_a_default_deny_policy_does_not_stop_an_agent_that_holds_a_skill_grant(
    programme: Programme,
    mandate_identity: MandateIdentity,
    repository_access: GitHubRepositoryAccess,
    tmp_path: Path,
) -> None:
    """A new agent holds a direct skills:create grant; under default-deny Paperclip still allows it."""
    with httpx.Client(
        base_url=mandate_identity.base_url,
        headers={"Origin": mandate_identity.base_url},
        timeout=60,
    ) as board:
        board.post(
            "/api/auth/sign-in/email",
            json={
                "email": mandate_identity.board_email,
                "password": mandate_identity.board_password,
            },
        ).raise_for_status()
        company = board.post("/api/companies", json={"name": "Default deny"}).raise_for_status()
        company_id = str(company.json()["id"])
        board.put(
            f"/api/companies/{company_id}/skill-policy",
            json={"schemaVersion": 1, "defaultEffect": "deny", "expectedRevision": 0, "rules": []},
        ).raise_for_status()
        agent = board.post(
            f"/api/companies/{company_id}/agents",
            json={
                "name": "Granted",
                "role": "engineer",
                "title": "Granted",
                "adapterType": "process",
                "adapterConfig": {"command": "true"},
            },
        ).raise_for_status()
        agent_id = str(agent.json()["id"])
        key = board.post(
            f"/api/agents/{agent_id}/keys", json={"name": "granted"}
        ).raise_for_status()
    token_file = tmp_path / "granted-token"
    token_file.write_text(str(key.json()["token"]), encoding="utf-8")
    service = PaperclipService(
        settings_for(
            mandate_identity, company_id=company_id, agent_id=agent_id, token_file=token_file
        )
    )
    await service.initialize()
    try:
        report = await ProgrammeReadinessService(service, repository_access).check(programme)
    finally:
        await service.close()

    causes = [
        f.cause for f in report.failures if f.check is ReadinessCheckType.MANDATE_AGENT_LIMITS
    ]
    assert any("Paperclip allows it skills.create (legacy_compatibility)" in c for c in causes)
