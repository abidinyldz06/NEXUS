"""Parameterized persistence for the disposable NEXUS SQLite index."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import NexusIndexError
from ..migrations import CURRENT_SCHEMA_VERSION, migrate

SEARCH_PROFILE_VERSION = 2


def configure_sqlite(connection: sqlite3.Connection, *, writable: bool) -> None:
    """Apply the same lock and durability pragmas on every NEXUS connection.

    Read-only connections only set ``busy_timeout``. Switching them to WAL would
    create sidecar files during a read. Writable connections use WAL, then
    :func:`seal_writable` returns the file to a single rollback database.
    """
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")
    if not writable:
        return
    connection.execute("PRAGMA synchronous = NORMAL")
    last_error: sqlite3.OperationalError | None = None
    for _ in range(50):
        try:
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
        except sqlite3.OperationalError as exc:
            last_error = exc
            time.sleep(0.01)
            continue
        if mode is not None and mode[0] == "wal":
            return
    raise sqlite3.OperationalError("journal_mode=WAL could not be set") from last_error


def seal_writable(connection: sqlite3.Connection) -> None:
    """Checkpoint and drop WAL sidecars so later reads do not create files."""
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("PRAGMA journal_mode = DELETE")
    except sqlite3.Error:
        pass


@contextmanager
def closing_writable(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Close a writable connection after checkpointing WAL back to one file."""
    try:
        yield connection
    finally:
        seal_writable(connection)
        connection.close()


@dataclass(frozen=True, slots=True)
class IndexedRecord:
    record_id: str
    kind: str
    status: str
    title: str
    body: str
    relative_path: str
    content_sha256: str
    payload: dict[str, Any]


class IndexStore:
    """Own one SQLite connection; callers control its filesystem lifecycle."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        try:
            if read_only:
                if path.is_symlink() or not path.is_file():
                    raise NexusIndexError("index does not exist as a regular file; run rebuild")
                uri = f"{path.resolve().as_uri()}?mode=ro"
                self.connection = sqlite3.connect(uri, uri=True)
            else:
                self.connection = sqlite3.connect(path)
        except sqlite3.Error as exc:
            raise NexusIndexError("cannot open SQLite index") from exc
        self.connection.row_factory = sqlite3.Row
        configure_sqlite(self.connection, writable=not read_only)

    def __enter__(self) -> IndexStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if not self.read_only:
            seal_writable(self.connection)
        self.connection.close()

    def migrate(self) -> int:
        if self.read_only:
            raise NexusIndexError("read-only index cannot be migrated")
        try:
            with self.connection:
                return migrate(self.connection)
        except sqlite3.Error as exc:
            raise NexusIndexError("SQLite migration failed") from exc

    def require_current_schema(self) -> None:
        try:
            row = self.connection.execute("SELECT version FROM schema_version").fetchone()
        except sqlite3.Error as exc:
            raise NexusIndexError("index schema metadata is missing; run rebuild") from exc
        if row is None or row[0] != CURRENT_SCHEMA_VERSION:
            raise NexusIndexError("index schema is not current; run rebuild")

    def require_current_search_profile(self) -> None:
        """Older derived indexes must be rebuilt before content search is shown."""
        self.require_current_schema()
        try:
            row = self.connection.execute(
                "SELECT version FROM search_profile WHERE id = 1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise NexusIndexError("index search profile is old; run rebuild") from exc
        if row is None or row[0] != SEARCH_PROFILE_VERSION:
            raise NexusIndexError("index search profile is old; run rebuild")

    def add_record(self, record: IndexedRecord) -> None:
        payload_json = json.dumps(
            record.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        try:
            self.connection.execute(
                """
                INSERT INTO records(
                    id, kind, status, title, body, relative_path, content_sha256, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.record_id,
                    record.kind,
                    record.status,
                    record.title,
                    record.body,
                    record.relative_path,
                    record.content_sha256,
                    payload_json,
                ),
            )
            self.connection.execute(
                "INSERT INTO records_fts(record_id, title, body, kind) VALUES (?, ?, ?, ?)",
                (record.record_id, record.title, record.body, record.kind),
            )
            if record.kind == "commitment":
                self.connection.execute(
                    """
                    INSERT INTO commitments(
                        record_id, status, due_date, due_time, timezone,
                        due_precision, notify, notified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.record_id,
                        record.status,
                        record.payload.get("due_date"),
                        record.payload.get("due_time"),
                        record.payload.get("timezone"),
                        record.payload.get("due_precision"),
                        int(bool(record.payload.get("notify", False))),
                        record.payload.get("notified_at"),
                    ),
                )
        except sqlite3.Error as exc:
            raise NexusIndexError(f"cannot index canonical record {record.record_id}") from exc

    def counts(self) -> tuple[int, int]:
        records = int(self.connection.execute("SELECT COUNT(*) FROM records").fetchone()[0])
        open_commitments = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM commitments WHERE status = ?", ("open",)
            ).fetchone()[0]
        )
        return records, open_commitments
