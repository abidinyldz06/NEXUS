"""Explicit, preconditioned forget workflow for one canonical record."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from .config import NexusConfig
from .errors import ForgetError, NexusIndexError
from .ids import IdPrefix, is_nexus_id, new_id
from .index import RebuildResult, rebuild_index
from .index.rebuild import scan_canonical_records
from .index.store import IndexedRecord
from .vault.paths import resolve_safe_vault_path
from .vault.rebuild_views import MemoryViewEntry, render_memory_view_entries


@dataclass(frozen=True, slots=True)
class ForgetPlan:
    record_id: str
    record_kind: str
    dependency_count: int
    dependency_kinds: dict[str, int]
    view_update_required: bool
    index_rebuild_required: bool = True

    @property
    def can_apply(self) -> bool:
        return self.dependency_count == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "dry-run",
            "writes_performed": False,
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "dependency_count": self.dependency_count,
            "dependency_kinds": dict(sorted(self.dependency_kinds.items())),
            "view_update_required": self.view_update_required,
            "index_rebuild_required": self.index_rebuild_required,
            "can_apply": self.can_apply,
        }


@dataclass(frozen=True, slots=True)
class ForgetResult:
    record_id: str
    record_kind: str
    records_after: int
    open_commitments_after: int
    index_sha256: str
    audit_written: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "confirmed-apply",
            "writes_performed": True,
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "deleted": True,
            "records_after": self.records_after,
            "open_commitments_after": self.open_commitments_after,
            "index_sha256": self.index_sha256,
            "audit_written": self.audit_written,
        }


@dataclass(frozen=True, slots=True)
class _ForgetAnalysis:
    target: IndexedRecord
    remaining: tuple[IndexedRecord, ...]
    plan: ForgetPlan


def _contains_exact(value: object, target_id: str) -> bool:
    if isinstance(value, str):
        return value == target_id
    if isinstance(value, list):
        return any(_contains_exact(item, target_id) for item in value)
    if isinstance(value, dict):
        return any(_contains_exact(item, target_id) for item in value.values())
    return False


def _analyze(vault_path: Path, record_id: str) -> _ForgetAnalysis:
    if not is_nexus_id(record_id) or record_id.startswith(f"{IdPrefix.RUN.value}_"):
        raise ForgetError("record_id must be a canonical NEXUS id")
    records = scan_canonical_records(vault_path)
    target = next((record for record in records if record.record_id == record_id), None)
    if target is None:
        raise ForgetError("canonical record was not found")
    remaining = tuple(record for record in records if record.record_id != record_id)
    dependent_kinds = Counter(
        record.kind for record in remaining if _contains_exact(record.payload, record_id)
    )
    plan = ForgetPlan(
        record_id=record_id,
        record_kind=target.kind,
        dependency_count=sum(dependent_kinds.values()),
        dependency_kinds=dict(dependent_kinds),
        view_update_required=target.kind == "memory",
    )
    return _ForgetAnalysis(target=target, remaining=remaining, plan=plan)


def plan_forget(config: NexusConfig, record_id: str) -> ForgetPlan:
    """Return target and dependency impact without changing any file."""
    if config.vault_path is None:
        raise ForgetError("vault_path is not configured")
    return _analyze(config.vault_path, record_id).plan


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ForgetError("forget target is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ForgetError("forget target cannot be opened safely") from exc
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ForgetError("forget output path cannot contain a symlink")
    descriptor, name = tempfile.mkstemp(prefix=".nexus-forget-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _render_memory_view(records: tuple[IndexedRecord, ...]) -> bytes:
    entries = (
        MemoryViewEntry(
            record_id=record.record_id,
            summary=record.title,
            status=record.status,
            relative_path=Path(record.relative_path),
        )
        for record in records
        if record.kind == "memory"
    )
    return render_memory_view_entries(entries).encode("utf-8")


def _append_audit(data_path: Path, payload: dict[str, object]) -> None:
    root = data_path.expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise ForgetError("data_path must be an absolute non-symlink path")
    directory = root / "forget"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ForgetError("forget audit directory cannot be a symlink")
    os.chmod(directory, 0o700)
    path = resolve_safe_vault_path(root, Path("forget") / "events.jsonl")
    if path.is_symlink():
        raise ForgetError("forget audit file cannot be a symlink")
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("short audit write")
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def _rollback_file(
    path: Path,
    original: bytes | None,
    *,
    expected_current: bytes | None,
) -> None:
    current = _read_regular(path) if path.exists() else None
    if current == original:
        return
    if current != expected_current:
        raise ForgetError("concurrent file change prevents safe rollback")
    if original is None:
        path.unlink(missing_ok=True)
        _fsync_directory(path.parent)
    else:
        _atomic_write(path, original)


def apply_forget(
    config: NexusConfig,
    record_id: str,
    *,
    confirmation: str,
    rebuild: Callable[[Path, Path], RebuildResult] = rebuild_index,
) -> ForgetResult:
    """Delete one unreferenced record after exact-ID confirmation and rebuild the index."""
    if confirmation != record_id:
        raise ForgetError("confirmation must exactly match record_id")
    if config.vault_path is None:
        raise ForgetError("vault_path is not configured")
    analysis = _analyze(config.vault_path, record_id)
    if not analysis.plan.can_apply:
        raise ForgetError("canonical record has dependent records; forget refused")

    target_path = resolve_safe_vault_path(config.vault_path, analysis.target.relative_path)
    target_before = _read_regular(target_path)
    expected_hash = analysis.target.content_sha256
    if sha256(target_before).hexdigest() != expected_hash:
        raise ForgetError("canonical record changed after impact analysis")

    view_path = resolve_safe_vault_path(
        config.vault_path, Path("Nexus") / "Views" / "Current-Memory.md"
    )
    view_before = _read_regular(view_path) if view_path.exists() else None
    index_before = _read_regular(config.index_path) if config.index_path.exists() else None
    new_view = (
        _render_memory_view(analysis.remaining) if analysis.plan.view_update_required else None
    )
    run_id = new_id(IdPrefix.RUN)

    target_deleted = view_changed = index_attempted = False
    rebuilt_index_hash: str | None = None
    try:
        current = _read_regular(target_path)
        if sha256(current).hexdigest() != expected_hash:
            raise ForgetError("canonical record changed before deletion")
        target_path.unlink()
        _fsync_directory(target_path.parent)
        target_deleted = True

        if new_view is not None:
            if view_before is None and view_path.exists():
                raise ForgetError("memory view appeared during forget")
            if view_before is not None and _read_regular(view_path) != view_before:
                raise ForgetError("memory view changed during forget")
            _atomic_write(view_path, new_view)
            view_changed = True

        index_attempted = True
        result = rebuild(config.vault_path, config.index_path)
        rebuilt_index_hash = result.database_sha256
        _append_audit(
            config.data_path,
            {
                "event_version": 1,
                "action": "forget",
                "run_id": run_id,
                "record_id": record_id,
                "record_kind": analysis.target.kind,
                "deleted_sha256": expected_hash,
                "dependency_count": 0,
                "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        )
    except Exception as exc:
        rollback_errors: list[str] = []
        target_current = _read_regular(target_path) if target_path.exists() else None
        view_current = _read_regular(view_path) if view_path.exists() else None
        index_current = (
            _read_regular(config.index_path) if config.index_path.exists() else None
        )
        if target_deleted and target_current not in {None, target_before}:
            rollback_errors.append("target")
        if view_changed and view_current not in {view_before, new_view}:
            rollback_errors.append("view")
        if index_attempted and index_current != index_before:
            current_hash = sha256(index_current).hexdigest() if index_current is not None else None
            if rebuilt_index_hash is None or current_hash != rebuilt_index_hash:
                rollback_errors.append("index")
        if rollback_errors:
            raise ForgetError(
                "forget failed and rollback was incomplete: " + ",".join(rollback_errors)
            ) from exc
        try:
            if target_deleted:
                _rollback_file(target_path, target_before, expected_current=None)
        except Exception:
            rollback_errors.append("target")
        try:
            if view_changed:
                _rollback_file(view_path, view_before, expected_current=new_view)
        except Exception:
            rollback_errors.append("view")
        try:
            if index_attempted:
                if index_current != index_before:
                    _rollback_file(
                        config.index_path,
                        index_before,
                        expected_current=index_current,
                    )
        except Exception:
            rollback_errors.append("index")
        if rollback_errors:
            raise ForgetError(
                "forget failed and rollback was incomplete: " + ",".join(rollback_errors)
            ) from exc
        if isinstance(exc, ForgetError):
            raise
        if isinstance(exc, (NexusIndexError, OSError, ValueError)):
            raise ForgetError("forget failed and exact prior state was restored") from exc
        raise

    return ForgetResult(
        record_id=record_id,
        record_kind=analysis.target.kind,
        records_after=result.records,
        open_commitments_after=result.open_commitments,
        index_sha256=result.database_sha256,
        audit_written=True,
    )


__all__ = ["ForgetPlan", "ForgetResult", "apply_forget", "plan_forget"]
