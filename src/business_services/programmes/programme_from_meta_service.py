"""Creates a programme on a Paperclip project from the configuration in a meta repo at a commit.

The configuration is read at the exact commit given, so the programme records what was read.
A programme whose project already exists is returned as it is: creating twice makes one project.
"""

from typing import Protocol

import yaml
from pydantic import ValidationError

from src.business_services.base_business_service import BaseBusinessService
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.paperclip_service import PaperclipService
from src.models.paperclip_models import NewProject
from src.models.programme_models import Programme, ProgrammeConfig

PROGRAMME_CONFIG_PATH = "config/programme.yaml"


class RepositoryAccessError(Exception):
    """A repository or file could not be reached; the message says why."""


class RepositoryAccess(Protocol):
    """Reads GitHub on behalf of the programme."""

    async def read_file(self, repo: str, path: str, ref: str) -> str:
        """The file's text at the ref; raise RepositoryAccessError when it cannot be read."""
        ...

    async def check_access(self, repo: str) -> None:
        """Return when the repo can be read; raise RepositoryAccessError with the cause."""
        ...


class ProgrammeConfigError(BaseAppException):
    """The meta repo's programme configuration could not be read or is not valid."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="PROGRAMME_CONFIG_INVALID", message=detail, status_code=422)


class ProgrammeFromMetaService(BaseBusinessService):
    """Reads a meta repo's Launchpad configuration and creates its programme in Paperclip."""

    def __init__(self, paperclip: PaperclipService, repositories: RepositoryAccess) -> None:
        super().__init__()
        self._paperclip = paperclip
        self._repositories = repositories

    async def create_programme(self, meta_repo: str, commit: str) -> Programme:
        """Read config/programme.yaml at `commit` and create the programme's project."""
        config = await self._read_config(meta_repo, commit)
        existing = [
            p for p in await self._paperclip.list_projects() if p.name == config.programme_slug
        ]
        if existing:
            return Programme(project_id=existing[0].id, meta_commit=commit, config=config)
        work_item = f"programme:{config.programme_slug}"
        run = await self._paperclip.open_run(work_item, "create")
        description = f"{config.programme} from {meta_repo}@{commit}\n\n{config.model_dump_json()}"
        project = await self._paperclip.create_project(
            run,
            work_item,
            "create",
            NewProject(name=config.programme_slug, description=description),
        )
        return Programme(project_id=project.id, meta_commit=commit, config=config)

    async def _read_config(self, meta_repo: str, commit: str) -> ProgrammeConfig:
        try:
            text = await self._repositories.read_file(meta_repo, PROGRAMME_CONFIG_PATH, commit)
            return ProgrammeConfig.model_validate(yaml.safe_load(text))
        except RepositoryAccessError as error:
            raise ProgrammeConfigError(f"cannot read {meta_repo}@{commit}: {error}") from error
        except (yaml.YAMLError, ValidationError) as error:
            raise ProgrammeConfigError(f"{PROGRAMME_CONFIG_PATH} is not valid: {error}") from error
