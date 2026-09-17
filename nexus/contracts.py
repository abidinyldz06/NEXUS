"""Versioned, provider-neutral NEXUS domain contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ContractError
from .ids import IdPrefix, is_nexus_id

SCHEMA_VERSION = 1


class SourceType(StrEnum):
    CHATGPT = "chatgpt"
    HERMES = "hermes"
    MANUAL = "manual"


class SourceAvailability(StrEnum):
    AVAILABLE = "available"
    EXCERPT_ONLY = "excerpt_only"
    DELETED = "deleted"


class MemoryType(StrEnum):
    FACT = "fact"
    EVENT = "event"
    DECISION = "decision"
    PREFERENCE = "preference"


class EntityType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PROJECT = "project"
    ASSET = "asset"
    PLACE = "place"


class Impact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RecordStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class ReviewStatus(StrEnum):
    AUTO = "auto"
    APPROVED = "approved"
    EDITED = "edited"
    PENDING = "pending"
    REJECTED = "rejected"
    EXPIRED = "expired"


class CommitmentStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class DuePrecision(StrEnum):
    EXACT = "exact"
    DAY = "day"
    RANGE = "range"
    AMBIGUOUS = "ambiguous"


def _require_id(value: str, prefix: IdPrefix, field_name: str) -> None:
    if not is_nexus_id(value, prefix):
        raise ContractError(f"{field_name} must be a {prefix.value}_ NEXUS id")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field_name} must not be empty")


def _require_confidence(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
        raise ContractError("confidence must be between 0 and 1")


def _require_enum(value: object, enum_type: type[StrEnum], field_name: str) -> None:
    if not isinstance(value, enum_type):
        raise ContractError(f"{field_name} must be a {enum_type.__name__}")


def _require_sha256(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ContractError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _require_datetime(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field_name} must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{field_name} must include a timezone offset")


def _require_optional_date(value: str | None, field_name: str) -> None:
    if value is None:
        return
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be an ISO 8601 date") from exc


def _require_optional_time(value: str | None, field_name: str) -> None:
    if value is None:
        return
    try:
        time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} must be an ISO 8601 time") from exc


def _require_source_refs(value: tuple[SourceRef, ...], field_name: str) -> None:
    if not value or any(not isinstance(item, SourceRef) for item in value):
        raise ContractError(f"{field_name} must contain at least one SourceRef")


def _require_schema_version(value: int) -> None:
    if value != SCHEMA_VERSION:
        raise ContractError(f"unsupported schema_version: {value}")


@dataclass(frozen=True, slots=True)
class SourceRef:
    source_id: str
    conversation_id: str
    span_ids: tuple[str, ...]
    span_sha256: str
    excerpt: str = ""

    def __post_init__(self) -> None:
        _require_id(self.source_id, IdPrefix.SOURCE, "source_id")
        _require_text(self.conversation_id, "conversation_id")
        if not self.span_ids or any(not str(item).strip() for item in self.span_ids):
            raise ContractError("span_ids must contain at least one non-empty id")
        _require_sha256(self.span_sha256, "span_sha256")
        if not isinstance(self.excerpt, str):
            raise ContractError("excerpt must be a string")
        if len(self.excerpt) > 500:
            raise ContractError("excerpt must be 500 characters or fewer")


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    source_type: SourceType
    content_sha256: str
    ingested_at: str
    external_id: str | None = None
    revision: int = 1
    message_count: int = 0
    source_started_at: str | None = None
    source_ended_at: str | None = None
    original_name: str = ""
    locator: str = ""
    parser: dict[str, str] = field(default_factory=dict)
    retained_until: str | None = None
    availability: SourceAvailability = SourceAvailability.AVAILABLE
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.id, IdPrefix.SOURCE, "id")
        _require_schema_version(self.schema_version)
        _require_enum(self.source_type, SourceType, "source_type")
        _require_sha256(self.content_sha256, "content_sha256")
        _require_datetime(self.ingested_at, "ingested_at")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or isinstance(self.message_count, bool)
            or not isinstance(self.message_count, int)
            or self.revision < 1
            or self.message_count < 0
        ):
            raise ContractError("revision must be positive and message_count cannot be negative")
        if self.source_started_at is not None:
            _require_datetime(self.source_started_at, "source_started_at")
        if self.source_ended_at is not None:
            _require_datetime(self.source_ended_at, "source_ended_at")
        if self.original_name:
            _require_text(self.original_name, "original_name")
            if "/" in self.original_name or "\\" in self.original_name:
                raise ContractError("original_name must be a basename")
        _require_optional_date(self.retained_until, "retained_until")
        _require_enum(self.availability, SourceAvailability, "availability")


@dataclass(frozen=True, slots=True)
class Memory:
    id: str
    type: MemoryType
    summary: str
    source_refs: tuple[SourceRef, ...]
    confidence: float
    impact: Impact
    review_status: ReviewStatus
    status: RecordStatus = RecordStatus.ACTIVE
    entity_ids: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: str | None = None
    extractor: dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.id, IdPrefix.MEMORY, "id")
        _require_schema_version(self.schema_version)
        _require_enum(self.type, MemoryType, "type")
        _require_text(self.summary, "summary")
        _require_confidence(self.confidence)
        _require_enum(self.impact, Impact, "impact")
        _require_enum(self.review_status, ReviewStatus, "review_status")
        _require_enum(self.status, RecordStatus, "status")
        _require_source_refs(self.source_refs, "source_refs")
        for entity_id in self.entity_ids:
            _require_id(entity_id, IdPrefix.ENTITY, "entity_ids item")
        for memory_id in self.supersedes:
            _require_id(memory_id, IdPrefix.MEMORY, "supersedes item")
        if self.superseded_by is not None:
            _require_id(self.superseded_by, IdPrefix.MEMORY, "superseded_by")


@dataclass(frozen=True, slots=True)
class Entity:
    id: str
    type: EntityType
    display_name: str
    normalized_name: str
    aliases: tuple[str, ...] = ()
    linked_notes: tuple[str, ...] = ()
    source_refs: tuple[SourceRef, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.id, IdPrefix.ENTITY, "id")
        _require_schema_version(self.schema_version)
        _require_enum(self.type, EntityType, "type")
        _require_text(self.display_name, "display_name")
        _require_text(self.normalized_name, "normalized_name")
        if any(not isinstance(item, SourceRef) for item in self.source_refs):
            raise ContractError("source_refs items must be SourceRef values")


@dataclass(frozen=True, slots=True)
class Relation:
    id: str
    from_entity_id: str
    predicate: str
    source_refs: tuple[SourceRef, ...]
    confidence: float
    impact: Impact
    to_entity_id: str | None = None
    literal: str | None = None
    status: RecordStatus = RecordStatus.ACTIVE
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.id, IdPrefix.RELATION, "id")
        _require_schema_version(self.schema_version)
        _require_id(self.from_entity_id, IdPrefix.ENTITY, "from_entity_id")
        _require_text(self.predicate, "predicate")
        _require_confidence(self.confidence)
        _require_enum(self.impact, Impact, "impact")
        _require_enum(self.status, RecordStatus, "status")
        if (self.to_entity_id is None) == (self.literal is None):
            raise ContractError("relation requires exactly one of to_entity_id or literal")
        if self.to_entity_id is not None:
            _require_id(self.to_entity_id, IdPrefix.ENTITY, "to_entity_id")
        if self.literal is not None:
            _require_text(self.literal, "literal")
        _require_source_refs(self.source_refs, "source_refs")


@dataclass(frozen=True, slots=True)
class Commitment:
    id: str
    summary: str
    actor_entity_id: str
    source_refs: tuple[SourceRef, ...]
    confidence: float
    impact: Impact
    review_status: ReviewStatus
    timezone: str
    due_date: str | None = None
    due_time: str | None = None
    due_precision: DuePrecision = DuePrecision.AMBIGUOUS
    target_entity_ids: tuple[str, ...] = ()
    status: CommitmentStatus = CommitmentStatus.OPEN
    notify: bool = False
    notified_at: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.id, IdPrefix.COMMITMENT, "id")
        _require_schema_version(self.schema_version)
        _require_id(self.actor_entity_id, IdPrefix.ENTITY, "actor_entity_id")
        _require_text(self.summary, "summary")
        _require_confidence(self.confidence)
        _require_enum(self.impact, Impact, "impact")
        _require_enum(self.review_status, ReviewStatus, "review_status")
        _require_enum(self.due_precision, DuePrecision, "due_precision")
        _require_enum(self.status, CommitmentStatus, "status")
        _require_source_refs(self.source_refs, "source_refs")
        for entity_id in self.target_entity_ids:
            _require_id(entity_id, IdPrefix.ENTITY, "target_entity_ids item")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ContractError(f"unknown timezone: {self.timezone}") from exc
        _require_optional_date(self.due_date, "due_date")
        _require_optional_time(self.due_time, "due_time")
        if not isinstance(self.notify, bool):
            raise ContractError("notify must be a boolean")
        if self.notified_at is not None:
            _require_datetime(self.notified_at, "notified_at")
        if self.notify and self.due_precision is DuePrecision.AMBIGUOUS:
            raise ContractError("ambiguous commitments cannot enable notifications")


@dataclass(frozen=True, slots=True)
class ReviewItem:
    id: str
    candidate_kind: str
    candidate_fingerprint: str
    reason_codes: tuple[str, ...]
    candidate: dict[str, Any]
    source_refs: tuple[SourceRef, ...]
    status: ReviewStatus = ReviewStatus.PENDING
    decision: dict[str, Any] | None = None
    publication: dict[str, Any] | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_id(self.id, IdPrefix.REVIEW, "id")
        _require_schema_version(self.schema_version)
        _require_text(self.candidate_kind, "candidate_kind")
        _require_text(self.candidate_fingerprint, "candidate_fingerprint")
        _require_enum(self.status, ReviewStatus, "status")
        if not self.reason_codes:
            raise ContractError("review item must include at least one reason code")
        _require_source_refs(self.source_refs, "source_refs")
        if self.decision is not None and not isinstance(self.decision, dict):
            raise ContractError("review decision must be an object or null")
        if self.publication is not None and not isinstance(self.publication, dict):
            raise ContractError("review publication must be an object or null")
