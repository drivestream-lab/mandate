"""PaperclipService comes from the DI container and reads its settings through get_instance()."""

from pathlib import Path

import pytest
from injector import Injector

from src.configs.paperclip_settings import PaperclipSettings
from src.di.modules.infra_module import InfraModule
from src.infra_services.paperclip_service import PaperclipService


def test_the_container_gives_one_service_built_from_the_settings_instance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PAPERCLIP_BASE_URL", "http://paperclip.invalid:3100")
    monkeypatch.setenv("PAPERCLIP_COMPANY_ID", "company-1")
    monkeypatch.setenv("PAPERCLIP_AGENT_ID", "agent-1")
    monkeypatch.setenv("PAPERCLIP_TOKEN_FILE", str(tmp_path / "token"))
    PaperclipSettings.clear_instances()
    try:
        injector = Injector([InfraModule()])
        service = injector.get(PaperclipService)

        assert service is injector.get(PaperclipService)
        assert service.agent_id == "agent-1"
    finally:
        PaperclipSettings.clear_instances()
