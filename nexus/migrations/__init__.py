"""SQLite schema migrations for the disposable NEXUS index."""

from .runner import CURRENT_SCHEMA_VERSION, migrate

__all__ = ["CURRENT_SCHEMA_VERSION", "migrate"]
