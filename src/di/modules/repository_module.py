"""Repository module for dependency injection."""

from injector import Binder, Module


class RepositoryModule(Module):
    """Bind repositories here as product features add schema tables."""

    def configure(self, binder: Binder) -> None:
        pass
