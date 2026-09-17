"""Explicit publication of approved memory review items to the canonical Vault."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .config import NexusConfig
from .contracts import Impact, Memory, MemoryType, ReviewItem, ReviewStatus
from .errors import ContractError, NexusIndexError, PublicationError, ReviewStoreError, VaultError
from .ids import IdPrefix, new_id
from .index import RebuildResult, rebuild_index
from .index.rebuild import scan_canonical_records
from .index.store import IndexedRecord
from .review import ReviewStore
from .serialization import to_primitive
from .vault import VaultRepository, VaultWrite, extract_record_payload
from .vault.rebuild_views import MemoryViewEntry, render_memory_view_entries

_REQUIRED_CANDIDATE_FIELDS = {"statement", "memory_type", "confidence", "impact"}
_OPTIONAL_CANDIDATE_FIELDS = {"entity_ids", "extractor"}


@dataclass(frozen=True, slots=True)
class PublicationPlan:
    review_id: str
    record_id: str
    record_kind: str
    review_status: str
    already_published: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "dry-run",
            "writes_performed": False,
            "review_id": self.review_id,
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "review_status": self.review_status,
            "already_published": self.already_published,
            "can_apply": True,
        }


@dataclass(frozen=True, slots=True)
class PublicationResult:
    review_id: str
    record_id: str
    content_sha256: str
    records_after: int
    already_published: bool
    writes_performed: bool
    vault_writes: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "confirmed-apply",
            "writes_performed": self.writes_performed,
            "vault_writes": self.vault_writes,
            "review_id": self.review_id,
            "record_id": self.record_id,
            "record_kind": "memory",
            "content_sha256": self.content_sha256,
            "records_after": self.records_after,
            "already_published": self.already_published,
        }


@dataclass(frozen=True, slots=True)
class _PublicationAnalysis:
    item: ReviewItem
    memory: Memory
    existing_hash: str | None
    records: tuple[IndexedRecord, ...]


def _record_id(review_id: str) -> str:
    prefix, separator, value = review_id.partition("_")
    if prefix != IdPrefix.REVIEW.value or not separator or len(value) != 32:
        raise PublicationError("review_id must be a valid NEXUS review id")
    return f"{IdPrefix.MEMORY.value}_{value}"


def _memory_from_review(item: ReviewItem) -> Memory:
    if item.status not in {ReviewStatus.APPROVED, ReviewStatus.EDITED}:
        raise PublicationError("only approved or edited review items can be published")
    if not isinstance(item.decision, dict) or item.decision.get("action") not in {
        "approve",
        "edit",
    }:
        raise PublicationError("review item has no valid approval audit")
    if item.candidate_kind != "memory":
        raise PublicationError("this publish slice supports memory review items only")
    candidate = item.candidate
    fields = set(candidate)
    if not _REQUIRED_CANDIDATE_FIELDS <= fields:
        raise PublicationError("memory candidate is missing required publication fields")
    if not fields <= _REQUIRED_CANDIDATE_FIELDS | _OPTIONAL_CANDIDATE_FIELDS:
        raise PublicationError("memory candidate has unsupported publication fields")
    statement = candidate.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        raise PublicationError("memory candidate statement must not be empty")
    entity_ids = candidate.get("entity_ids", [])
    extractor = candidate.get("extractor", {})
    if not isinstance(entity_ids, list) or not isinstance(extractor, dict):
        raise PublicationError("memory candidate metadata is invalid")
    try:
        memory_type = MemoryType(candidate["memory_type"])
        impact = Impact(candidate["impact"])
        confidence = candidate["confidence"]
        enriched_extractor = dict(extractor)
        enriched_extractor.update({"source": "review", "review_id": item.id})
        return Memory(
            id=_record_id(item.id),
            type=memory_type,
            summary=statement.strip(),
            source_refs=item.source_refs,
            confidence=confidence,
            impact=impact,
            review_status=item.status,
            entity_ids=tuple(entity_ids),
            extractor=enriched_extractor,
        )
    except (ContractError, TypeError, ValueError, VaultError) as exc:
        raise PublicationError("memory candidate cannot form a canonical record") from exc


def _analyze(config: NexusConfig, review_id: str) -> _PublicationAnalysis:
    if config.vault_path is None:
        raise PublicationError("vault_path is not configured")
    item = ReviewStore(config.data_path).get(review_id)
    memory = _memory_from_review(item)
    records = scan_canonical_records(config.vault_path)
    entities = {record.record_id for record in records if record.kind == "entity"}
    if any(entity_id not in entities for entity_id in memory.entity_ids):
        raise PublicationError("memory candidate references a missing canonical entity")
    existing = next((record for record in records if record.record_id == memory.id), None)
    if existing is not None:
        if existing.kind != "memory" or existing.payload != to_primitive(memory):
            raise PublicationError("deterministic canonical target has conflicting content")
        if item.publication is not None:
            if (
                item.publication.get("record_id") != memory.id
                or item.publication.get("content_sha256") != existing.content_sha256
            ):
                raise PublicationError("review publication audit conflicts with canonical data")
        existing_hash = existing.content_sha256
    else:
        if item.publication is not None:
            raise PublicationError("review claims publication but canonical record is missing")
        existing_hash = None
    return _PublicationAnalysis(
        item=item,
        memory=memory,
        existing_hash=existing_hash,
        records=records,
    )


def plan_publication(config: NexusConfig, review_id: str) -> PublicationPlan:
    analysis = _analyze(config, review_id)
    return PublicationPlan(
        review_id=review_id,
        record_id=analysis.memory.id,
        record_kind="memory",
        review_status=analysis.item.status.value,
        already_published=analysis.existing_hash is not None,
    )


def _read_optional(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise PublicationError("publication state path is not a regular file")
    return path.read_bytes()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise PublicationError("publication rollback path cannot contain a symlink")
    descriptor, name = tempfile.mkstemp(prefix=".nexus-publish-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _view_write(
    analysis: _PublicationAnalysis,
    repository: VaultRepository,
    before: bytes | None,
) -> VaultWrite:
    entries = [
        MemoryViewEntry(
            record_id=record.record_id,
            summary=record.title,
            status=record.status,
            relative_path=Path(record.relative_path),
        )
        for record in analysis.records
        if record.kind == "memory"
    ]
    entries.append(
        MemoryViewEntry(
            record_id=analysis.memory.id,
            summary=analysis.memory.summary,
            status=analysis.memory.status.value,
            relative_path=repository.record_path(analysis.memory),
        )
    )
    return VaultWrite(
        Path("Nexus/Views/Current-Memory.md"),
        render_memory_view_entries(entries).encode("utf-8"),
        sha256(before).hexdigest() if before is not None else None,
    )


def _rollback_new_publication(
    *,
    target_path: Path,
    created_hash: str,
    view_path: Path,
    view_before: bytes | None,
    view_after: bytes,
) -> None:
    current_target = _read_optional(target_path)
    current_view = _read_optional(view_path)
    if current_target is None or sha256(current_target).hexdigest() != created_hash:
        raise PublicationError("publication rollback refused a concurrent target change")
    if current_view != view_after:
        raise PublicationError("publication rollback refused a concurrent view change")
    target_path.unlink()
    _fsync_directory(target_path.parent)
    if view_before is None:
        view_path.unlink()
        _fsync_directory(view_path.parent)
    else:
        _atomic_write(view_path, view_before)


def apply_publication(
    config: NexusConfig,
    review_id: str,
    *,
    confirmation: str,
    rebuild: Callable[[Path, Path], RebuildResult] = rebuild_index,
) -> PublicationResult:
    if confirmation != review_id:
        raise PublicationError("confirmation must exactly match review_id")
    analysis = _analyze(config, review_id)
    assert config.vault_path is not None
    store = ReviewStore(config.data_path)
    run_id = new_id(IdPrefix.RUN)

    if analysis.existing_hash is not None:
        audit_missing = analysis.item.publication is None
        if audit_missing:
            rebuild_result = rebuild(config.vault_path, config.index_path)
            store.record_publication(
                review_id,
                record_id=analysis.memory.id,
                content_sha256=analysis.existing_hash,
                run_id=run_id,
            )
            records_after = rebuild_result.records
        else:
            records_after = len(analysis.records)
        return PublicationResult(
            review_id=review_id,
            record_id=analysis.memory.id,
            content_sha256=analysis.existing_hash,
            records_after=records_after,
            already_published=True,
            writes_performed=audit_missing,
            vault_writes=False,
        )

    repository = VaultRepository(config.vault_path)
    target_path = config.vault_path / repository.record_path(analysis.memory)
    view_path = config.vault_path / "Nexus" / "Views" / "Current-Memory.md"
    view_before = _read_optional(view_path)
    index_before = _read_optional(config.index_path)
    view_write = _view_write(analysis, repository, view_before)
    try:
        repository.commit_records(
            (analysis.memory,),
            run_id=run_id,
            generated_writes=(view_write,),
        )
        created_hash = repository.current_hash(analysis.memory)
    except (VaultError, OSError) as exc:
        raise PublicationError("canonical publication transaction failed") from exc

    try:
        rebuild_result = rebuild(config.vault_path, config.index_path)
    except (NexusIndexError, OSError, ValueError) as exc:
        try:
            _rollback_new_publication(
                target_path=target_path,
                created_hash=created_hash,
                view_path=view_path,
                view_before=view_before,
                view_after=view_write.content,
            )
            current_index = _read_optional(config.index_path)
            if current_index != index_before:
                raise PublicationError("index changed during failed publication rebuild")
        except (PublicationError, OSError) as rollback_error:
            raise PublicationError(
                "index rebuild failed and publication rollback was incomplete"
            ) from rollback_error
        raise PublicationError(
            "index rebuild failed; canonical publication was rolled back"
        ) from exc

    try:
        store.record_publication(
            review_id,
            record_id=analysis.memory.id,
            content_sha256=created_hash,
            run_id=run_id,
        )
    except (ReviewStoreError, OSError) as exc:
        raise PublicationError(
            "canonical publication committed but review audit is incomplete; retry"
        ) from exc

    return PublicationResult(
        review_id=review_id,
        record_id=analysis.memory.id,
        content_sha256=created_hash,
        records_after=rebuild_result.records,
        already_published=False,
        writes_performed=True,
        vault_writes=True,
    )


__all__ = [
    "PublicationPlan",
    "PublicationResult",
    "apply_publication",
    "plan_publication",
]
