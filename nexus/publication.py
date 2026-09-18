"""Explicit publication of approved review items to the canonical Vault."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .config import NexusConfig
from .contracts import (
    Commitment,
    DuePrecision,
    Entity,
    EntityType,
    Impact,
    Memory,
    MemoryType,
    ReviewItem,
    ReviewStatus,
)
from .entity import normalize_alias
from .errors import ContractError, NexusIndexError, PublicationError, ReviewStoreError, VaultError
from .ids import IdPrefix, new_id
from .index import RebuildResult, rebuild_index
from .index.rebuild import scan_canonical_records
from .index.store import IndexedRecord
from .review import ReviewStore
from .serialization import to_primitive
from .vault import VaultRepository, VaultWrite
from .vault.rebuild_views import MemoryViewEntry, render_memory_view_entries

_MEMORY_REQUIRED_FIELDS = {"statement", "memory_type", "confidence", "impact"}
_MEMORY_OPTIONAL_FIELDS = {"entity_ids", "extractor"}
_ENTITY_FIELDS = {
    "display_name",
    "normalized_name",
    "entity_type",
    "aliases",
    "linked_notes",
    "extractor",
}
_COMMITMENT_FIELDS = {
    "statement",
    "actor_entity_id",
    "confidence",
    "impact",
    "timezone",
    "due_date",
    "due_time",
    "due_precision",
    "target_entity_ids",
    "notify",
    "extractor",
}

PublishRecord = Memory | Entity | Commitment


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
    record_kind: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "confirmed-apply",
            "writes_performed": self.writes_performed,
            "vault_writes": self.vault_writes,
            "review_id": self.review_id,
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "content_sha256": self.content_sha256,
            "records_after": self.records_after,
            "already_published": self.already_published,
        }


@dataclass(frozen=True, slots=True)
class _PublicationAnalysis:
    item: ReviewItem
    record: PublishRecord
    record_kind: str
    existing_hash: str | None
    records: tuple[IndexedRecord, ...]


def _record_id(review_id: str, record_prefix: IdPrefix) -> str:
    review_prefix, separator, value = review_id.partition("_")
    if review_prefix != IdPrefix.REVIEW.value or not separator or len(value) != 32:
        raise PublicationError("review_id must be a valid NEXUS review id")
    return f"{record_prefix.value}_{value}"


def _require_approved(item: ReviewItem) -> None:
    if item.status not in {ReviewStatus.APPROVED, ReviewStatus.EDITED}:
        raise PublicationError("only approved or edited review items can be published")
    if not isinstance(item.decision, dict) or item.decision.get("action") not in {
        "approve",
        "edit",
    }:
        raise PublicationError("review item has no valid approval audit")


def _memory_from_review(item: ReviewItem) -> Memory:
    candidate = item.candidate
    fields = set(candidate)
    if not _MEMORY_REQUIRED_FIELDS <= fields:
        raise PublicationError("memory candidate is missing required publication fields")
    if not fields <= _MEMORY_REQUIRED_FIELDS | _MEMORY_OPTIONAL_FIELDS:
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
            id=_record_id(item.id, IdPrefix.MEMORY),
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


def _commitment_from_review(item: ReviewItem) -> Commitment:
    candidate = item.candidate
    if set(candidate) != _COMMITMENT_FIELDS:
        raise PublicationError("commitment candidate must match the closed publication shape")
    statement = candidate.get("statement")
    target_entity_ids = candidate.get("target_entity_ids")
    extractor = candidate.get("extractor")
    if not isinstance(statement, str) or not statement.strip():
        raise PublicationError("commitment candidate statement must not be empty")
    if not isinstance(target_entity_ids, list) or not isinstance(extractor, dict):
        raise PublicationError("commitment candidate metadata is invalid")
    try:
        enriched_extractor = dict(extractor)
        enriched_extractor.update({"source": "review", "review_id": item.id})
        return Commitment(
            id=_record_id(item.id, IdPrefix.COMMITMENT),
            summary=statement.strip(),
            actor_entity_id=candidate["actor_entity_id"],
            source_refs=item.source_refs,
            confidence=candidate["confidence"],
            impact=Impact(candidate["impact"]),
            review_status=item.status,
            timezone=candidate["timezone"],
            due_date=candidate["due_date"],
            due_time=candidate["due_time"],
            due_precision=DuePrecision(candidate["due_precision"]),
            target_entity_ids=tuple(target_entity_ids),
            notify=candidate["notify"],
            extractor=enriched_extractor,
        )
    except (ContractError, KeyError, TypeError, ValueError, VaultError) as exc:
        raise PublicationError("commitment candidate cannot form a canonical record") from exc


def _entity_from_review(item: ReviewItem) -> Entity:
    candidate = item.candidate
    if set(candidate) != _ENTITY_FIELDS:
        raise PublicationError("entity candidate must match the closed publication shape")
    display_name = candidate.get("display_name")
    normalized_name = candidate.get("normalized_name")
    aliases = candidate.get("aliases")
    linked_notes = candidate.get("linked_notes")
    extractor = candidate.get("extractor")
    if not isinstance(display_name, str) or not display_name.strip():
        raise PublicationError("entity candidate display_name must not be empty")
    if not isinstance(normalized_name, str) or not normalized_name.strip():
        raise PublicationError("entity candidate normalized_name must not be empty")
    if normalized_name != normalize_alias(display_name):
        raise PublicationError("entity candidate normalized_name must match display_name")
    if not isinstance(aliases, list) or not isinstance(linked_notes, list):
        raise PublicationError("entity candidate aliases and linked_notes must be arrays")
    if not isinstance(extractor, dict):
        raise PublicationError("entity candidate extractor must be an object")
    try:
        return Entity(
            id=_record_id(item.id, IdPrefix.ENTITY),
            type=EntityType(candidate["entity_type"]),
            display_name=display_name.strip(),
            normalized_name=normalized_name,
            aliases=tuple(aliases),
            linked_notes=tuple(linked_notes),
            source_refs=item.source_refs,
        )
    except (ContractError, KeyError, TypeError, ValueError, VaultError) as exc:
        raise PublicationError("entity candidate cannot form a canonical record") from exc


def _record_from_review(item: ReviewItem) -> tuple[PublishRecord, str]:
    _require_approved(item)
    if item.candidate_kind == "memory":
        return _memory_from_review(item), "memory"
    if item.candidate_kind == "commitment":
        return _commitment_from_review(item), "commitment"
    if item.candidate_kind == "entity":
        return _entity_from_review(item), "entity"
    raise PublicationError(
        "this publish slice supports memory, commitment or entity review items only"
    )


def _entity_names(payload: dict[str, object]) -> set[str]:
    values = [payload.get("display_name"), payload.get("normalized_name")]
    aliases = payload.get("aliases", [])
    if isinstance(aliases, list):
        values.extend(aliases)
    return {normalize_alias(value) for value in values if isinstance(value, str) and value.strip()}


def _entity_linked_notes(payload: dict[str, object]) -> set[str]:
    linked_notes = payload.get("linked_notes", [])
    if not isinstance(linked_notes, list):
        return set()
    return {value for value in linked_notes if isinstance(value, str) and value.strip()}


def _analyze(config: NexusConfig, review_id: str) -> _PublicationAnalysis:
    if config.vault_path is None:
        raise PublicationError("vault_path is not configured")
    item = ReviewStore(config.data_path).get(review_id)
    record, record_kind = _record_from_review(item)
    records = scan_canonical_records(config.vault_path)
    entities = {indexed.record_id for indexed in records if indexed.kind == "entity"}
    if isinstance(record, Memory):
        referenced_entities = record.entity_ids
    elif isinstance(record, Commitment):
        referenced_entities = (record.actor_entity_id, *record.target_entity_ids)
    else:
        referenced_entities = ()
    if any(entity_id not in entities for entity_id in referenced_entities):
        raise PublicationError(f"{record_kind} candidate references a missing canonical entity")
    if isinstance(record, Entity):
        candidate_names = {
            normalize_alias(record.display_name),
            normalize_alias(record.normalized_name),
            *(normalize_alias(alias) for alias in record.aliases),
        }
        candidate_notes = set(record.linked_notes)
        collision = any(
            indexed.kind == "entity"
            and indexed.payload.get("type") == record.type.value
            and (
                bool(candidate_names & _entity_names(indexed.payload))
                or bool(candidate_notes & _entity_linked_notes(indexed.payload))
            )
            for indexed in records
            if indexed.record_id != record.id
        )
        if collision:
            raise PublicationError(
                "entity candidate conflicts with an existing exact typed alias or linked note"
            )
    existing = next((item for item in records if item.record_id == record.id), None)
    if existing is not None:
        if existing.kind != record_kind or existing.payload != to_primitive(record):
            raise PublicationError("deterministic canonical target has conflicting content")
        if item.publication is not None:
            if (
                item.publication.get("record_id") != record.id
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
        record=record,
        record_kind=record_kind,
        existing_hash=existing_hash,
        records=records,
    )


def plan_publication(config: NexusConfig, review_id: str) -> PublicationPlan:
    analysis = _analyze(config, review_id)
    return PublicationPlan(
        review_id=review_id,
        record_id=analysis.record.id,
        record_kind=analysis.record_kind,
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
    if not isinstance(analysis.record, Memory):
        raise PublicationError("only memory publication updates Current-Memory view")
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
            record_id=analysis.record.id,
            summary=analysis.record.summary,
            status=analysis.record.status.value,
            relative_path=repository.record_path(analysis.record),
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
    view_path: Path | None,
    view_before: bytes | None,
    view_after: bytes | None,
) -> None:
    current_target = _read_optional(target_path)
    if current_target is None or sha256(current_target).hexdigest() != created_hash:
        raise PublicationError("publication rollback refused a concurrent target change")
    if view_path is not None:
        current_view = _read_optional(view_path)
        if view_after is None or current_view != view_after:
            raise PublicationError("publication rollback refused a concurrent view change")
    target_path.unlink()
    _fsync_directory(target_path.parent)
    if view_path is not None:
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
                record_id=analysis.record.id,
                content_sha256=analysis.existing_hash,
                run_id=run_id,
            )
            records_after = rebuild_result.records
        else:
            records_after = len(analysis.records)
        return PublicationResult(
            review_id=review_id,
            record_id=analysis.record.id,
            content_sha256=analysis.existing_hash,
            records_after=records_after,
            already_published=True,
            writes_performed=audit_missing,
            vault_writes=False,
            record_kind=analysis.record_kind,
        )

    repository = VaultRepository(config.vault_path)
    target_path = config.vault_path / repository.record_path(analysis.record)
    view_path = (
        config.vault_path / "Nexus" / "Views" / "Current-Memory.md"
        if analysis.record_kind == "memory"
        else None
    )
    view_before = _read_optional(view_path) if view_path is not None else None
    index_before = _read_optional(config.index_path)
    view_write = (
        _view_write(analysis, repository, view_before)
        if view_path is not None
        else None
    )
    try:
        repository.commit_records(
            (analysis.record,),
            run_id=run_id,
            generated_writes=(view_write,) if view_write is not None else (),
        )
        created_hash = repository.current_hash(analysis.record)
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
                view_after=view_write.content if view_write is not None else None,
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
            record_id=analysis.record.id,
            content_sha256=created_hash,
            run_id=run_id,
        )
    except (ReviewStoreError, OSError) as exc:
        raise PublicationError(
            "canonical publication committed but review audit is incomplete; retry"
        ) from exc

    return PublicationResult(
        review_id=review_id,
        record_id=analysis.record.id,
        content_sha256=created_hash,
        records_after=rebuild_result.records,
        already_published=False,
        writes_performed=True,
        vault_writes=True,
        record_kind=analysis.record_kind,
    )


__all__ = [
    "PublicationPlan",
    "PublicationResult",
    "apply_publication",
    "plan_publication",
]
