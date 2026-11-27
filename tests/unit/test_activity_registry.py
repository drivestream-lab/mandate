"""Every activity name a workflow may call is registered with the worker."""

from src.models.workflow_activity_models import ActivityNameType
from src.worker_main import registered_activity_names


def test_every_activity_name_is_registered() -> None:
    assert set(ActivityNameType) <= registered_activity_names()


def test_only_known_activity_names_are_registered() -> None:
    assert registered_activity_names() <= set(ActivityNameType)
