"""Contract: Mandate works only against the pinned Paperclip release; anything else is a stop."""

import pytest

from src.configs.paperclip_settings import PINNED_PAPERCLIP_COMMIT
from src.infra_services.paperclip_service import (
    PaperclipError,
    PaperclipService,
    UnrecognisedReleaseError,
)
from tests.contract.paperclip.conftest import settings_for
from tests.contract.paperclip.paperclip_stack import MandateIdentity

pytestmark = pytest.mark.req("REQ-40")


async def test_the_run_stack_reports_the_pinned_release(
    paperclip: PaperclipService,
) -> None:
    await paperclip.verify_release()

    assert await paperclip.health_check() is True
    assert PINNED_PAPERCLIP_COMMIT.startswith("a665ed6")


async def test_a_different_pinned_release_stops_the_client_before_any_work(
    mandate_identity: MandateIdentity,
) -> None:
    other_release = "0" * 40
    service = PaperclipService(settings_for(mandate_identity), pinned_commit=other_release)

    with pytest.raises(UnrecognisedReleaseError, match="not the pinned release"):
        await service.initialize()

    assert await service.health_check() is False


async def test_no_run_can_be_opened_after_the_release_was_refused(
    mandate_identity: MandateIdentity,
) -> None:
    service = PaperclipService(settings_for(mandate_identity), pinned_commit="1" * 40)
    with pytest.raises(UnrecognisedReleaseError):
        await service.initialize()

    with pytest.raises(PaperclipError, match="not initialised"):
        await service.open_run("work-item", "step")


async def test_an_unreachable_paperclip_is_an_unknown_release_and_stops(
    mandate_identity: MandateIdentity,
) -> None:
    service = PaperclipService(settings_for(mandate_identity, base_url="http://127.0.0.1:1"))

    with pytest.raises(UnrecognisedReleaseError, match="could not be read"):
        await service.initialize()
