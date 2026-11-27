"""PostgreSQL settings for mandate."""

import os
from pathlib import Path
from typing import ClassVar, Optional, TypedDict
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, computed_field, model_validator

from src.configs.base_settings import BaseSettings


class EngineArgs(TypedDict):
    """Keyword arguments for create_async_engine."""

    pool_pre_ping: bool
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    connect_args: dict[str, object]


class PostgresSettings(BaseSettings):
    """Settings for PostgreSQL database connection."""

    PREFIX: ClassVar[str] = "POSTGRES"

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    user: str = Field(description="PostgreSQL user (POSTGRES_USER); no default")
    password_file: Path = Field(
        description="File holding the service's password (POSTGRES_PASSWORD_FILE); no default"
    )
    migration_user: Optional[str] = Field(
        default=None,
        description="Migration role (mandate_owner); used by the migration step only, never by the service",
    )
    migration_password_file: Optional[Path] = Field(
        default=None,
        description="File holding the migration role's password; the entrypoint removes the path before the service starts",
    )
    db: str = Field(
        default="ds_mandate_db",
        description="PostgreSQL database name",
    )
    min_pool_size: int = Field(default=5, description="Minimum connection pool size")
    max_pool_size: int = Field(default=20, description="Maximum connection pool size")
    pool_timeout: int = Field(default=30, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=1800, description="Pool recycle interval in seconds")
    use_ssl: bool = Field(default=False, description="Use SSL for connection")
    ssl_mode: Optional[str] = Field(default=None, description="SSL mode")
    connect_timeout: int = Field(default=10, description="Connection timeout in seconds")
    command_timeout: int = Field(default=30, description="Command timeout in seconds")

    @model_validator(mode="after")
    def refuse_passwords_in_the_environment(self) -> "PostgresSettings":
        for key in ("POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD", "PGPASSWORD"):
            if key in os.environ:
                raise ValueError(
                    f"{key} is set; passwords are read from the POSTGRES_*_FILE files, never from the environment"
                )
        return self

    @staticmethod
    def _read_password(variable: str, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise ValueError(f"{variable}: {path} is missing or unreadable") from error

    @property
    def password(self) -> SecretStr:
        return SecretStr(self._read_password("POSTGRES_PASSWORD_FILE", self.password_file))

    @computed_field
    @property
    def sqlalchemy_database_uri(self) -> str:
        password = quote_plus(self.password.get_secret_value())
        return f"postgresql+asyncpg://{self.user}:{password}@{self.host}:{self.port}/{self.db}"

    @property
    def alembic_database_uri(self) -> str:
        """Migration connection: the owner's credentials, never the service's."""
        if not self.migration_user:
            raise ValueError(
                "POSTGRES_MIGRATION_USER is not set; migrations never use the app role"
            )
        if self.migration_password_file is None:
            raise ValueError(
                "POSTGRES_MIGRATION_PASSWORD_FILE is not set; migrations never use the app role"
            )
        password = quote_plus(
            self._read_password("POSTGRES_MIGRATION_PASSWORD_FILE", self.migration_password_file)
        )
        conn_str = (
            f"postgresql+psycopg2://{self.migration_user}:{password}"
            f"@{self.host}:{self.port}/{self.db}"
        )
        if self.use_ssl:
            conn_str += f"?sslmode={'require' if not self.ssl_mode else self.ssl_mode}"
        return conn_str

    @computed_field
    @property
    def sqlalchemy_engine_args(self) -> EngineArgs:
        connect_args: dict[str, object] = {
            "timeout": self.connect_timeout,
            "command_timeout": self.command_timeout,
            "server_settings": {"application_name": "mandate"},
        }
        if self.use_ssl:
            connect_args["ssl"] = "require" if not self.ssl_mode else self.ssl_mode
        return {
            "pool_pre_ping": True,
            "pool_size": self.min_pool_size,
            "max_overflow": self.max_pool_size - self.min_pool_size,
            "pool_timeout": self.pool_timeout,
            "pool_recycle": self.pool_recycle,
            "connect_args": connect_args,
        }
