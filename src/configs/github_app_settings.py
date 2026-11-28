"""Settings for Mandate's GitHub App: where its credentials are, never the credentials."""

from pathlib import Path
from typing import ClassVar

from pydantic import Field

from src.configs.base_settings import BaseSettings


class GitHubAppSettings(BaseSettings):
    """Paths of Mandate's App credential files and the organisation it works in."""

    PREFIX: ClassVar[str] = "GITHUB_APP"

    app_id_file: Path = Field(description="File holding the App id")
    installation_id_file: Path = Field(description="File holding the installation id")
    private_key_file: Path = Field(description="File holding the App's private key (PEM)")
    owner: str = Field(default="drivestream-lab", min_length=1)
    api_url: str = Field(default="https://api.github.com")
    request_timeout_seconds: float = Field(default=30.0, gt=0)
