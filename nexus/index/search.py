"""Read-only, parameterized FTS5 search."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..errors import NexusIndexError
from .store import IndexStore

_QUERY_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SearchResult:
    record_id: str
    kind: str
    status: str
    title: str
    relative_path: str
    content_sha256: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.record_id,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "snippet": self.snippet,
        }


def _fts_expression(query: str) -> str:
    if len(query) > 500:
        raise NexusIndexError("search query must be 500 characters or fewer")
    tokens = _QUERY_TOKEN.findall(query)
    if not tokens:
        raise NexusIndexError("search query must contain at least one letter or number")
    if len(tokens) > 50:
        raise NexusIndexError("search query must contain 50 terms or fewer")
    return " AND ".join(f'"{token}"' for token in tokens)


def search_index(
    index_path: Path,
    query: str,
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> tuple[SearchResult, ...]:
    if not 1 <= limit <= 100:
        raise NexusIndexError("search limit must be between 1 and 100")
    expression = _fts_expression(query)
    sql = """
        SELECT r.id, r.kind, r.status, r.title, r.relative_path, r.content_sha256,
               snippet(records_fts, 2, '[', ']', ' … ', 12) AS result_snippet
        FROM records_fts
        JOIN records AS r ON r.id = records_fts.record_id
        WHERE records_fts MATCH ?
          AND (? IS NULL OR r.kind = ?)
          AND (? IS NULL OR r.status = ?)
        ORDER BY bm25(records_fts), r.id
        LIMIT ?
    """
    try:
        with IndexStore(index_path, read_only=True) as store:
            store.require_current_schema()
            rows = store.connection.execute(
                sql, (expression, kind, kind, status, status, limit)
            ).fetchall()
    except sqlite3.Error as exc:
        raise NexusIndexError("SQLite search failed") from exc
    return tuple(
        SearchResult(
            record_id=row["id"],
            kind=row["kind"],
            status=row["status"],
            title=row["title"],
            relative_path=row["relative_path"],
            content_sha256=row["content_sha256"],
            snippet=row["result_snippet"],
        )
        for row in rows
    )
