"""Typed names and payloads for the activities Temporal workflows call."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ActivityNameType(StrEnum):
    """Every business-service activity a workflow may call, by name.

    A name is added here together with its input and output models and its registration in
    worker_main.py; a unit test fails when one is missing from the registry.
    """


class ActivityInput(BaseModel):
    """Base of every activity input model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ActivityOutput(BaseModel):
    """Base of every activity output model."""

    model_config = ConfigDict(frozen=True, extra="forbid")
