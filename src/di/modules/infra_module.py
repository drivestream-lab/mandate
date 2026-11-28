"""Infrastructure services module for dependency injection."""

from injector import Binder, Module, singleton

from src.database.postgres.connection_manager import PostgresConnectionManager
from src.database.redis.connection_manager import RedisConnectionManager
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.paperclip_service import PaperclipService
from src.infra_services.postgres_service import PostgresService
from src.infra_services.redis_service import RedisService
from src.infra_services.telemetry_service import TelemetryService
from src.logging import get_logger

logger = get_logger()


class InfraModule(Module):
    """Register core infrastructure services."""

    def configure(self, binder: Binder) -> None:
        logger.info("Configuring infrastructure services module")
        binder.bind(PostgresConnectionManager, to=PostgresConnectionManager, scope=singleton)
        binder.bind(RedisConnectionManager, to=RedisConnectionManager, scope=singleton)
        binder.bind(PostgresService, to=PostgresService, scope=singleton)
        binder.bind(RedisService, to=RedisService, scope=singleton)
        binder.bind(TelemetryService, scope=singleton)
        binder.bind(PaperclipService, to=PaperclipService, scope=singleton)
        binder.bind(GitHubAppService, to=GitHubAppService, scope=singleton)
        logger.debug("Infrastructure services module configured")
