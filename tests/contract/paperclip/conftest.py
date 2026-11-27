"""Fixtures for the Paperclip contract tests: Mandate's identity in the run's own Paperclip."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pytest import TempPathFactory

from src.configs.paperclip_settings import PaperclipSettings
from src.infra_services.paperclip_service import PaperclipService
from tests.contract.paperclip.paperclip_stack import MandateIdentity, provision_once
from tests.journeys.journey_support import StackAddresses


@pytest.fixture(scope="session")
def mandate_identity(
    journey_stack: StackAddresses, tmp_path_factory: TempPathFactory
) -> MandateIdentity:
    """A company, a project and Mandate's restricted agent in this run's Paperclip."""
    token_file = tmp_path_factory.mktemp("paperclip-token") / "mandate-token"
    return provision_once(journey_stack.paperclip_url, token_file)


def settings_for(identity: MandateIdentity, **overrides: str | Path) -> PaperclipSettings:
    """Settings that point Mandate at the provisioned identity, with any field replaced."""
    fields: dict[str, str | Path] = {
        "base_url": identity.base_url,
        "company_id": identity.company_id,
        "agent_id": identity.agent_id,
        "project_id": identity.project_id,
        "token_file": identity.token_file,
    }
    fields.update(overrides)
    return PaperclipSettings.model_validate(fields)


@pytest.fixture
async def paperclip(mandate_identity: MandateIdentity) -> AsyncIterator[PaperclipService]:
    """Mandate's client, ready on the pinned release."""
    service = PaperclipService(settings_for(mandate_identity))
    await service.initialize()
    try:
        yield service
    finally:
        await service.close()
