"""API utilities and helpers for Parichay."""

from functools import wraps
from collections.abc import Awaitable, Callable
from typing import Any, ParamSpec, TypeVar

from fastapi import HTTPException

from src.logging import get_logger
from src.exceptions.app_exceptions import BaseAppException

logger = get_logger()

P = ParamSpec("P")
R = TypeVar("R")


def _path_log_context(kwargs: dict[str, Any]) -> dict[str, str]:
    """Extract searchable path params from handler kwargs for error logs."""
    context: dict[str, str] = {}
    for key in ("tenant_id", "user_id", "device_id", "credential_id", "catalog_id"):
        value = kwargs.get(key)
        if value is not None:
            context[key] = str(value)
    return context


def handle_api_errors(
    operation_name: str, error_context: str = "API"
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator for consistent error handling across API endpoints."""

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            path_context = _path_log_context(kwargs)
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                raise
            except BaseAppException as e:
                logger.error(
                    "Application error in API handler",
                    error_context=error_context,
                    operation=operation_name,
                    code=e.code,
                    message=e.message,
                    **path_context,
                )
                raise HTTPException(status_code=e.status_code, detail=e.message)
            except ValueError as e:
                logger.error(
                    "Value error in API handler",
                    error_context=error_context,
                    operation=operation_name,
                    error=str(e),
                    **path_context,
                )
                raise HTTPException(status_code=404, detail=str(e))
            except Exception as e:
                logger.error(
                    "Unexpected error in API handler",
                    error_context=error_context,
                    operation=operation_name,
                    error=str(e),
                    exc_info=True,
                    **path_context,
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to {operation_name.lower()}: {str(e)}",
                )

        return wrapper

    return decorator
