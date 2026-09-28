"""Parameterized persistence for the disposable NEXUS SQLite index."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import NexusIndexError
from ..migrations import CURRENT_SCHEMA_VERSION, migrate

SEARCH_PROFILE_VERSION = 2


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
        self.connection.execute("PRAGMA foreign_keys = ON")

    def __enter__(self) -> IndexStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
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
