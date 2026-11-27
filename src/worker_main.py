"""Temporal worker entrypoint: the registry of business-service activities.

Each ActivityNameType value maps to the activity that serves it. There are no activities
yet, so the registry is empty; a unit test keeps the enum and the registry in step.
"""

from collections.abc import Awaitable, Callable

from src.models.workflow_activity_models import ActivityInput, ActivityNameType, ActivityOutput

ActivityHandler = Callable[[ActivityInput], Awaitable[ActivityOutput]]

ACTIVITY_REGISTRY: dict[ActivityNameType, ActivityHandler] = {}


def registered_activity_names() -> frozenset[ActivityNameType]:
    """Names the worker registers an activity for."""
    return frozenset(ACTIVITY_REGISTRY)
