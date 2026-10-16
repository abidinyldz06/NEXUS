"""Due commitment scanner with canonical notified-at idempotency."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..commitments import commitment_from_payload, is_due, mark_notified
from ..contracts import Commitment
from ..errors import NexusIndexError, PulseError, VaultError
from ..ids import IdPrefix, new_id
from ..index import IndexStore, rebuild_index
from ..vault import VaultRepository, VaultTransaction, VaultWrite
from ..vault.paths import resolve_safe_vault_path


@dataclass(frozen=True, slots=True)
class DueCommitment:
    commitment: Commitment
    relative_path: str
    content_sha256: str


def scan_due_commitments(
    index_path: Path,
    *,
    now: datetime,
    limit: int = 20,
) -> tuple[DueCommitment, ...]:
    if now.tzinfo is None:
        raise PulseError("now must include a timezone offset")
    if not 1 <= limit <= 20:
        raise PulseError("reminder digest limit must be between 1 and 20")
    try:
        with IndexStore(index_path, read_only=True) as store:
            store.require_current_schema()
            rows = store.connection.execute(
                """
                SELECT r.payload_json, r.relative_path, r.content_sha256
                FROM commitments AS c
                JOIN records AS r ON r.id = c.record_id
                WHERE c.status = ? AND c.notify = 1 AND c.notified_at IS NULL
                ORDER BY c.due_date, c.due_time, c.record_id
                """,
                ("open",),
            ).fetchall()
    except NexusIndexError:
        raise
    except sqlite3.Error as exc:
        raise PulseError("cannot read the reminder queue") from exc
    due: list[DueCommitment] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise PulseError("indexed commitment payload is invalid") from exc
        commitment = commitment_from_payload(payload)
        if is_due(commitment, now=now):
            due.append(
                DueCommitment(
                    commitment=commitment,
                    relative_path=row["relative_path"],
                    content_sha256=row["content_sha256"],
                )
            )
        if len(due) == limit:
            break
    return tuple(due)


def _safe_line(value: str, *, limit: int = 240) -> str:
    compact = " ".join(value.split())
    cleaned = "".join(character for character in compact if character.isprintable())
    return cleaned[:limit]


def _render_digest(items: tuple[DueCommitment, ...]) -> str:
    lines = [f"NEXUS hatırlatmaları ({len(items)})"]
    for item in items:
        reference = item.commitment.source_refs[0]
        spans = ", ".join(reference.span_ids)
        lines.extend(
            [
                f"- {_safe_line(item.commitment.summary)}",
                f"  Kaynak: {reference.source_id} / {_safe_line(spans, limit=160)}",
            ]
        )
    return "\n".join(lines)


def emit_due_reminders(
    vault_path: Path,
    index_path: Path,
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> str:
    """Atomically mark due canonical commitments, rebuild, then return local output."""
    instant = now or datetime.now(UTC)
    items = scan_due_commitments(index_path, now=instant, limit=limit)
    if not items:
        return ""
    repository = VaultRepository(vault_path)
    expected_hashes: dict[str, str] = {}
    original_writes: list[VaultWrite] = []
    updated: list[Commitment] = []
    for item in items:
        expected_path = repository.record_path(item.commitment).as_posix()
        if item.relative_path != expected_path:
            raise PulseError("indexed commitment path does not match its canonical id")
        canonical_path = resolve_safe_vault_path(vault_path, expected_path)
        if canonical_path.is_symlink() or not canonical_path.is_file():
            raise PulseError("canonical commitment is not a regular file")
        original_writes.append(VaultWrite(Path(expected_path), canonical_path.read_bytes()))
        expected_hashes[item.commitment.id] = item.content_sha256
        updated.append(mark_notified(item.commitment, now=instant))
    try:
        repository.commit_records(
            updated,
            run_id=new_id(IdPrefix.RUN),
            expected_hashes=expected_hashes,
        )
    except (VaultError, OSError) as exc:
        raise PulseError("reminder state could not be committed safely") from exc
    try:
        rebuild_index(vault_path, index_path)
    except (NexusIndexError, OSError) as rebuild_error:
        rollback_writes: list[VaultWrite] = []
        try:
            for original, changed in zip(original_writes, updated, strict=True):
                rollback_writes.append(
                    VaultWrite(
                        original.relative_path,
                        original.content,
                        repository.current_hash(changed),
                    )
                )
            VaultTransaction(vault_path).commit(
                rollback_writes,
                run_id=new_id(IdPrefix.RUN),
            )
        except (VaultError, OSError) as rollback_error:
            raise PulseError(
                "index rebuild failed and canonical reminder rollback was incomplete"
            ) from rollback_error
        raise PulseError(
            "index rebuild failed; canonical reminder state was rolled back"
        ) from rebuild_error
    return _render_digest(items)
