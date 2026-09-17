"""Small forward-only migration runner for a rebuildable database."""

from __future__ import annotations

import importlib
import sqlite3
from datetime import UTC, datetime

from ..errors import NexusIndexError

CURRENT_SCHEMA_VERSION = 1
_MIGRATIONS = (".001_initial",)


def _installed_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    versions = connection.execute("SELECT version FROM schema_version").fetchall()
    if len(versions) != 1 or not isinstance(versions[0][0], int):
        raise NexusIndexError("index schema_version metadata is invalid")
    return int(versions[0][0])


def migrate(connection: sqlite3.Connection) -> int:
    """Apply known migrations and reject indexes newer than this package."""
    current = _installed_version(connection)
    if current > CURRENT_SCHEMA_VERSION:
        raise NexusIndexError(
            f"index schema {current} is newer than supported {CURRENT_SCHEMA_VERSION}"
        )
    for module_name in _MIGRATIONS[current:]:
        module = importlib.import_module(module_name, package=__package__)
        expected = current + 1
        if expected != module.VERSION:
            raise NexusIndexError("index migration sequence is invalid")
        module.apply(connection)
        connection.execute("DELETE FROM schema_version")
        connection.execute(
            "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
            (module.VERSION, datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        )
        current = module.VERSION
    connection.execute("PRAGMA user_version = 1")
    return current
