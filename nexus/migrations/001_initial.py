"""Initial FTS5 and structured index schema."""

from __future__ import annotations

import sqlite3
from importlib.resources import files

VERSION = 1


def apply(connection: sqlite3.Connection) -> None:
    schema = files("nexus.index").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
