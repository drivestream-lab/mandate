"""The release check on reports a live Paperclip does not produce: no commit, a short commit."""

import pytest

from src.configs.paperclip_settings import PINNED_PAPERCLIP_COMMIT
from src.infra_services.paperclip_service import UnrecognisedReleaseError, check_release
from src.models.paperclip_models import HealthStatusType, PaperclipHealth

pytestmark = pytest.mark.req("REQ-40")


def test_the_pinned_commit_is_recognised() -> None:
    check_release(
        PaperclipHealth(status=HealthStatusType.OK, commit=PINNED_PAPERCLIP_COMMIT),
        PINNED_PAPERCLIP_COMMIT,
    )


def test_a_starting_paperclip_is_a_stop_whatever_its_commit() -> None:
    with pytest.raises(UnrecognisedReleaseError, match="starting"):
        check_release(
            PaperclipHealth(status=HealthStatusType.STARTING, commit=PINNED_PAPERCLIP_COMMIT),
            PINNED_PAPERCLIP_COMMIT,
        )


@pytest.mark.parametrize("reported", [None, "", PINNED_PAPERCLIP_COMMIT[:7], "f" * 40])
def test_anything_else_is_a_stop(reported: str | None) -> None:
    with pytest.raises(UnrecognisedReleaseError):
        check_release(
            PaperclipHealth(status=HealthStatusType.OK, commit=reported), PINNED_PAPERCLIP_COMMIT
        )
