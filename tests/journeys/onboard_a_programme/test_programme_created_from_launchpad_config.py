"""Journey: a programme is created on a Paperclip project from the meta repo's configuration."""

import pytest

from src.business_services.programmes.programme_from_meta_service import (
    ProgrammeConfigError,
    ProgrammeFromMetaService,
)
from src.infra_services.paperclip_service import PaperclipService
from src.models.programme_models import RungType
from tests.journeys.onboard_a_programme.conftest import META_REPO

pytestmark = pytest.mark.req("REQ-01")


async def test_programme_is_created_from_the_configuration_at_a_commit(
    programme_from_meta: ProgrammeFromMetaService, paperclip: PaperclipService, meta_commit: str
) -> None:
    programme = await programme_from_meta.create_programme(META_REPO, meta_commit)

    config = programme.config
    assert programme.meta_commit == meta_commit
    assert config.repos == ("mandate-sandbox-meta", "mandate-sandbox-svc")
    assert [(r.name, r.agent) for r in config.roles] == [
        ("coder", "sandbox-coder"),
        ("design-decider", "sandbox-design-decider"),
    ]
    assert config.decision_owners.release == "kd"
    assert (config.workflow.contract, config.workflow.version) == ("sdd-delivery/v2", "v0.5.6")
    assert config.starting_rung is RungType.L0
    projects = {p.id: p for p in await paperclip.list_projects()}
    assert projects[programme.project_id].name == "mandate-sandbox"
    assert meta_commit in (projects[programme.project_id].description or "")


async def test_creating_the_programme_twice_makes_one_project(
    programme_from_meta: ProgrammeFromMetaService, paperclip: PaperclipService, meta_commit: str
) -> None:
    first = await programme_from_meta.create_programme(META_REPO, meta_commit)
    second = await programme_from_meta.create_programme(META_REPO, meta_commit)

    assert first.project_id == second.project_id
    assert [p.name for p in await paperclip.list_projects()].count("mandate-sandbox") == 1


async def test_a_commit_without_the_configuration_names_the_cause(
    programme_from_meta: ProgrammeFromMetaService,
) -> None:
    with pytest.raises(ProgrammeConfigError, match="GitHub answered 404"):
        await programme_from_meta.create_programme(META_REPO, "0" * 40)
