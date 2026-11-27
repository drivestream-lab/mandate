"""Paperclip settings: where it is, which identity Mandate acts as, and the one release it may run on."""

from pathlib import Path
from typing import ClassVar

from pydantic import Field

from src.configs.base_settings import BaseSettings

PINNED_PAPERCLIP_COMMIT = "a665ed6a1b990a96f11f73ea7bd73a8228e511e9"
"""The build commit of the Paperclip baseline Mandate was tested against (image tag mandate-baseline-a665ed6)."""


class PaperclipSettings(BaseSettings):
    """Settings for Mandate's identity in Paperclip. The token is read from a file, never held here."""

    PREFIX: ClassVar[str] = "PAPERCLIP"

    base_url: str = Field(description="Paperclip's address, for example http://paperclip:3100")
    company_id: str = Field(min_length=1, description="The Paperclip company Mandate works in")
    agent_id: str = Field(min_length=1, description="Mandate's own agent; every run is woken on it")
    project_id: str | None = Field(default=None, description="Project new issues are filed under")
    token_file: Path = Field(description="Path of the file holding Mandate's agent token")
    pinned_commit: str = Field(
        default=PINNED_PAPERCLIP_COMMIT,
        pattern=r"^[0-9a-f]{40}$",
        description="The only Paperclip build commit Mandate runs against",
    )
    request_timeout_seconds: float = Field(default=30.0, gt=0)
