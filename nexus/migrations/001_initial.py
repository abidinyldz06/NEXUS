"""Initial FTS5 and structured index schema."""

from __future__ import annotations

import sqlite3
from importlib.resources import files

VERSION = 1


def apply(connection: sqlite3.Connection) -> None:
    plugin_package = __package__.rsplit(".", 1)[0]
    schema = (
        files(f"{plugin_package}.index").joinpath("schema.sql").read_text(encoding="utf-8")
    )
    connection.executescript(schema)
