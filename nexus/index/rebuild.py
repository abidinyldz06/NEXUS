"""Rebuild the entire derived SQLite index from canonical Markdown records."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..contracts import SCHEMA_VERSION
from ..errors import NexusIndexError, VaultError
from ..ids import IdPrefix, is_nexus_id
from ..vault import extract_record_payload
from .store import IndexedRecord, IndexStore

_CANONICAL_ROOTS = {
    "Memory": ("memory", IdPrefix.MEMORY),
    "Entities": ("entity", IdPrefix.ENTITY),
    "Relations": ("relation", IdPrefix.RELATION),
    "Commitments": ("commitment", IdPrefix.COMMITMENT),
    "Sources": ("source", IdPrefix.SOURCE),
    "Review": ("review", IdPrefix.REVIEW),
}


@dataclass(frozen=True, slots=True)
class RebuildResult:
    records: int
    open_commitments: int
    index_path: Path
    database_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "records": self.records,
            "open_commitments": self.open_commitments,
            "index_path": str(self.index_path),
            "database_sha256": self.database_sha256,
            "vault_writes": False,
        }


def _text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_text_values(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_text_values(item))
        return result
    return []


def _record_fields(kind: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    if kind == "memory":
        return str(payload.get("summary", "")), str(payload.get("status", "active")), " ".join(
            _text_values(payload)
        )
    if kind == "entity":
        return str(payload.get("display_name", "")), "active", " ".join(_text_values(payload))
    if kind == "relation":
        return str(payload.get("predicate", "")), str(payload.get("status", "active")), " ".join(
            _text_values(payload)
        )
    if kind == "commitment":
        return str(payload.get("summary", "")), str(payload.get("status", "open")), " ".join(
            _text_values(payload)
        )
    if kind == "source":
        title = payload.get("original_name") or payload.get("locator") or payload.get("id", "")
        return str(title), str(payload.get("availability", "available")), " ".join(
            _text_values(payload)
        )
    if kind == "review":
        return (
            str(payload.get("candidate_kind", "")),
            str(payload.get("status", "pending")),
            " ".join(_text_values(payload)),
        )
    raise NexusIndexError(f"unsupported canonical record kind: {kind}")


def _load_record(vault_root: Path, path: Path, kind: str, prefix: IdPrefix) -> IndexedRecord:
    if path.is_symlink() or not path.is_file():
        raise NexusIndexError(f"canonical record is not a regular file: {path}")
    try:
        content = path.read_bytes()
        markdown = content.decode("utf-8")
        payload = extract_record_payload(markdown)
    except (OSError, UnicodeError, VaultError) as exc:
        raise NexusIndexError(f"cannot read canonical record: {path}") from exc
    record_id = payload.get("id")
    if not isinstance(record_id, str) or not is_nexus_id(record_id, prefix):
        raise NexusIndexError(f"canonical record id does not match its path: {path}")
    if path.stem != record_id:
        raise NexusIndexError(f"canonical record filename does not match payload id: {path}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NexusIndexError(f"unsupported canonical schema version: {path}")
    title, status, body = _record_fields(kind, payload)
    if not title.strip():
        raise NexusIndexError(f"canonical record has no searchable title: {path}")
    relative = path.relative_to(vault_root)
    return IndexedRecord(
        record_id=record_id,
        kind=kind,
        status=status,
        title=title,
        body=body,
        relative_path=relative.as_posix(),
        content_sha256=sha256(content).hexdigest(),
        payload=payload,
    )


def scan_canonical_records(vault_root: Path) -> tuple[IndexedRecord, ...]:
    if vault_root.is_symlink() or not vault_root.is_dir():
        raise NexusIndexError("vault_path must be an existing non-symlink directory")
    nexus_root = vault_root / "Nexus"
    if nexus_root.is_symlink():
        raise NexusIndexError("Nexus canonical root cannot be a symlink")
    records: list[IndexedRecord] = []
    for directory, (kind, prefix) in _CANONICAL_ROOTS.items():
        root = nexus_root / directory
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise NexusIndexError(f"canonical directory is unsafe: {root}")
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(vault_root)
            current = vault_root
            for component in relative.parts:
                current = current / component
                if current.is_symlink():
                    raise NexusIndexError(f"canonical path contains a symlink: {path}")
            records.append(_load_record(vault_root, path, kind, prefix))
    ids = [record.record_id for record in records]
    if len(ids) != len(set(ids)):
        raise NexusIndexError("duplicate canonical record id found")
    return tuple(records)


def rebuild_index(vault_root: Path, index_path: Path) -> RebuildResult:
    """Build beside the live DB, then atomically replace it after a complete scan."""
    records = scan_canonical_records(vault_root)
    parent = index_path.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise NexusIndexError("index parent must be a non-symlink directory")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(parent, 0o700)
    if index_path.is_symlink():
        raise NexusIndexError("index path cannot be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nexus-rebuild-", suffix=".db", dir=parent
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        os.chmod(temporary_path, 0o600)
        with IndexStore(temporary_path) as store:
            store.migrate()
            try:
                with store.connection:
                    for record in records:
                        store.add_record(record)
            except Exception:
                store.connection.rollback()
                raise
            counts = store.counts()
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_path, index_path)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return RebuildResult(
        records=counts[0],
        open_commitments=counts[1],
        index_path=index_path,
        database_sha256=sha256(index_path.read_bytes()).hexdigest(),
    )
