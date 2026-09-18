"""Exact-source ingestion planning, shadow extraction and private review staging."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any

from .config import NexusConfig
from .commitments import resolve_due
from .contracts import DuePrecision, Impact, Source, SourceAvailability, SourceRef
from .errors import ParseError, SourceError
from .entity import normalize_alias
from .extraction.schema import CandidateKind, ExtractionCandidate
from .extraction.service import PROMPT_VERSION, ExtractionOutcome, ExtractionService
from .fingerprints import stable_hash
from .policy import PolicyAction, PolicyInput, evaluate_policy
from .raw_store import DiscoveredSource, RawStore, discover_inbox, read_discovered
from .review import ReviewStore, create_review_item
from .segmenter import ConversationSegment, segment_conversation
from .sources import ChatGPTAdapter, HermesAdapter, ManualAdapter, ParsedSource, SourceAdapter
from .state import SourceObservation, SourceStateStore


@dataclass(frozen=True, slots=True)
class DryRunItem:
    relative_path: str
    source_type: str
    adapter: str
    conversations: int
    messages: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class DryRunFailure:
    relative_path: str
    reason: str


@dataclass(frozen=True, slots=True)
class DryRunReport:
    inbox: str
    accepted: tuple[DryRunItem, ...]
    rejected: tuple[DryRunFailure, ...]
    writes_performed: bool = False

    @property
    def ok(self) -> bool:
        return not self.rejected

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": "dry-run",
            "writes_performed": self.writes_performed,
            "inbox": self.inbox,
            "accepted": [asdict(item) for item in self.accepted],
            "rejected": [asdict(item) for item in self.rejected],
            "summary": {
                "files": len(self.accepted),
                "conversations": sum(item.conversations for item in self.accepted),
                "messages": sum(item.messages for item in self.accepted),
                "rejected": len(self.rejected),
            },
        }


@dataclass(frozen=True, slots=True)
class ShadowIngestReport:
    source_type: str
    adapter: str
    source_sha256: str
    conversations: int
    messages: int
    segments: int
    segment_limit: int
    candidates: int
    candidate_kinds: dict[str, int]
    warnings: int
    providers: tuple[str, ...]
    models: tuple[str, ...]
    agent_ids: tuple[str, ...]
    prompt_version: str
    prompt_sha256: str
    successful_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "shadow",
            "writes_performed": False,
            "candidates_published": False,
            "source": {
                "type": self.source_type,
                "adapter": self.adapter,
                "sha256": self.source_sha256,
                "conversations": self.conversations,
                "messages": self.messages,
            },
            "extraction": {
                "segments": self.segments,
                "segment_limit": self.segment_limit,
                "candidates": self.candidates,
                "candidate_kinds": dict(self.candidate_kinds),
                "warnings": self.warnings,
            },
            "audit": {
                "providers": list(self.providers),
                "models": list(self.models),
                "agent_ids": list(self.agent_ids),
                "prompt_version": self.prompt_version,
                "prompt_sha256": self.prompt_sha256,
                "successful_calls": self.successful_calls,
                "usage": {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "total_tokens": self.total_tokens,
                },
            },
        }


@dataclass(frozen=True, slots=True)
class StagedIngestReport:
    source_type: str
    adapter: str
    source_sha256: str
    conversations: int
    messages: int
    segments: int
    candidates: int
    review_items_created: int
    review_items_reused: int
    discarded: int
    quarantined: int
    source_revision: int
    duplicate_source: bool
    raw_disposition: str
    writes_performed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "stage",
            "writes_performed": self.writes_performed,
            "vault_writes": False,
            "candidates_published": False,
            "source": {
                "type": self.source_type,
                "adapter": self.adapter,
                "sha256": self.source_sha256,
                "conversations": self.conversations,
                "messages": self.messages,
                "revision": self.source_revision,
                "duplicate": self.duplicate_source,
                "raw_disposition": self.raw_disposition,
            },
            "extraction": {
                "segments": self.segments,
                "candidates": self.candidates,
                "discarded": self.discarded,
                "quarantined": self.quarantined,
            },
            "review": {
                "created": self.review_items_created,
                "reused": self.review_items_reused,
            },
        }


@dataclass(frozen=True, slots=True)
class _PreparedIngest:
    source: DiscoveredSource
    parsed: ParsedSource
    conversation_index: int
    segments: tuple[ConversationSegment, ...]


ADAPTERS: tuple[SourceAdapter, ...] = (ChatGPTAdapter(), HermesAdapter(), ManualAdapter())


def parse_discovered(source: DiscoveredSource) -> ParsedSource:
    payload = read_discovered(source)
    for adapter in ADAPTERS:
        if adapter.supports(source.path, payload[:16384]):
            return adapter.parse_bytes(payload, original_name=source.path.name)
    raise ParseError("no adapter recognizes this supported extension")


def plan_inbox(config: NexusConfig) -> DryRunReport:
    discovery = discover_inbox(
        config.inbox_path,
        max_source_bytes=config.max_source_bytes,
        stable_seconds=config.source_stable_seconds,
    )
    accepted: list[DryRunItem] = []
    rejected = [DryRunFailure(item.relative_path, item.reason) for item in discovery.rejected]
    for source in discovery.accepted:
        try:
            parsed = parse_discovered(source)
        except SourceError as exc:
            rejected.append(DryRunFailure(source.relative_path, str(exc)))
            continue
        accepted.append(
            DryRunItem(
                relative_path=source.relative_path,
                source_type=parsed.source_type.value,
                adapter=f"{parsed.adapter_name}@{parsed.adapter_version}",
                conversations=len(parsed.conversations),
                messages=parsed.message_count,
                content_sha256=source.content_sha256,
            )
        )
    return DryRunReport(
        inbox=str(config.inbox_path), accepted=tuple(accepted), rejected=tuple(rejected)
    )


def shadow_inbox_source(
    config: NexusConfig,
    llm: object,
    *,
    relative_path: str,
    confirmed_sha256: str,
    conversation_id: str | None = None,
    max_segments: int = 20,
    max_segment_chars: int = 12_000,
    max_attempts: int = 2,
) -> ShadowIngestReport:
    """Run one exact Inbox source through extraction without persisting content."""
    prepared = _prepare_exact_source(
        config,
        relative_path=relative_path,
        confirmed_sha256=confirmed_sha256,
        conversation_id=conversation_id,
        max_segments=max_segments,
        max_segment_chars=max_segment_chars,
    )
    service = ExtractionService(llm, max_attempts=max_attempts)
    outcomes = tuple(service.extract(segment) for segment in prepared.segments)
    kind_counts: Counter[str] = Counter(
        candidate.kind.value
        for outcome in outcomes
        for candidate in outcome.result.candidates
    )
    audits = [outcome.audit for outcome in outcomes]
    return ShadowIngestReport(
        source_type=prepared.parsed.source_type.value,
        adapter=f"{prepared.parsed.adapter_name}@{prepared.parsed.adapter_version}",
        source_sha256=prepared.source.content_sha256,
        conversations=1,
        messages=len(prepared.parsed.conversations[prepared.conversation_index].messages),
        segments=len(prepared.segments),
        segment_limit=max_segments,
        candidates=sum(len(outcome.result.candidates) for outcome in outcomes),
        candidate_kinds=dict(sorted(kind_counts.items())),
        warnings=sum(len(outcome.result.warnings) for outcome in outcomes),
        providers=tuple(sorted({audit.provider for audit in audits if audit.provider})),
        models=tuple(sorted({audit.model for audit in audits if audit.model})),
        agent_ids=tuple(sorted({audit.agent_id for audit in audits if audit.agent_id})),
        prompt_version=audits[0].prompt_version if audits else PROMPT_VERSION,
        prompt_sha256=service.prompt_sha256,
        successful_calls=len(audits),
        input_tokens=sum(audit.input_tokens for audit in audits),
        output_tokens=sum(audit.output_tokens for audit in audits),
        total_tokens=sum(audit.total_tokens for audit in audits),
    )


def _prepare_exact_source(
    config: NexusConfig,
    *,
    relative_path: str,
    confirmed_sha256: str,
    conversation_id: str | None,
    max_segments: int,
    max_segment_chars: int,
) -> _PreparedIngest:
    selected_path = PurePosixPath(relative_path)
    if (
        not relative_path
        or selected_path.is_absolute()
        or ".." in selected_path.parts
        or selected_path.as_posix() in {"", "."}
    ):
        raise SourceError("source must be a safe Inbox-relative path")
    if (
        len(confirmed_sha256) != 64
        or any(character not in "0123456789abcdef" for character in confirmed_sha256)
    ):
        raise SourceError("confirm-sha must be a lowercase SHA-256 digest")
    if isinstance(max_segments, bool) or not 1 <= max_segments <= 100:
        raise SourceError("max-segments must be between 1 and 100")

    discovery = discover_inbox(
        config.inbox_path,
        max_source_bytes=config.max_source_bytes,
        stable_seconds=config.source_stable_seconds,
    )
    matches = [item for item in discovery.accepted if item.relative_path == relative_path]
    if len(matches) != 1:
        rejected = next(
            (item for item in discovery.rejected if item.relative_path == relative_path),
            None,
        )
        if rejected is not None:
            raise SourceError(f"selected source is not eligible: {rejected.reason}")
        raise SourceError("selected source was not found")
    source = matches[0]
    if source.content_sha256 != confirmed_sha256:
        raise SourceError("confirmation SHA does not match selected source")

    try:
        parsed = parse_discovered(source)
    except SourceError as exc:
        raise SourceError("selected source could not be parsed safely") from exc
    if conversation_id is None:
        if len(parsed.conversations) != 1:
            raise SourceError("multi-conversation sources require --conversation")
        conversation_index = 0
    else:
        indexes = tuple(
            index
            for index, item in enumerate(parsed.conversations)
            if item.external_conversation_id == conversation_id
        )
        if len(indexes) != 1:
            raise SourceError("selected conversation was not found uniquely")
        conversation_index = indexes[0]
    conversation = parsed.conversations[conversation_index]
    segments = tuple(
        segment_conversation(conversation, max_chars=max_segment_chars)
    )
    if not segments:
        raise SourceError("selected source contains no extractable segments")
    if len(segments) > max_segments:
        raise SourceError("selected conversation exceeds max-segments before model execution")

    return _PreparedIngest(
        source=source,
        parsed=parsed,
        conversation_index=conversation_index,
        segments=segments,
    )


def _source_ref(
    source_id: str,
    segment: ConversationSegment,
    candidate: ExtractionCandidate,
) -> SourceRef:
    by_id = {message.message_id: message for message in segment.messages}
    evidence = tuple(
        (span_id, by_id[span_id].content_sha256) for span_id in candidate.source_span_ids
    )
    return SourceRef(
        source_id=source_id,
        conversation_id=segment.conversation_id,
        span_ids=candidate.source_span_ids,
        span_sha256=stable_hash(evidence),
    )


def _source_timestamp(
    segment: ConversationSegment,
    candidate: ExtractionCandidate,
) -> str | None:
    cited = set(candidate.source_span_ids)
    timestamps = sorted(
        message.created_at
        for message in segment.messages
        if message.message_id in cited and message.created_at is not None
    )
    return timestamps[0] if timestamps else None


def _policy_input(
    candidate: ExtractionCandidate,
    segment: ConversationSegment,
    *,
    timezone_name: str,
) -> PolicyInput:
    cited = set(candidate.source_span_ids)
    user_asserted = any(
        message.message_id in cited and message.role == "user" for message in segment.messages
    )
    due_precision = None
    if candidate.kind is CandidateKind.COMMITMENT:
        source_at = _source_timestamp(segment, candidate)
        if source_at is None:
            due_precision = DuePrecision.AMBIGUOUS
        else:
            due_precision = resolve_due(
                candidate.statement,
                source_at=source_at,
                timezone=timezone_name,
            ).due_precision
    return PolicyInput(
        kind=candidate.kind,
        statement=candidate.statement,
        confidence=candidate.confidence,
        source_span_ids=candidate.source_span_ids,
        impact=Impact.LOW,
        due_precision=due_precision,
        ambiguity_flags=candidate.ambiguity_flags,
        user_asserted=user_asserted,
    )


def _review_candidate(
    candidate: ExtractionCandidate,
    outcome: ExtractionOutcome,
    decision_action: PolicyAction,
    *,
    impact: Impact,
    sensitivity: str,
    segment: ConversationSegment,
    timezone_name: str,
) -> dict[str, Any]:
    audit = outcome.audit
    extractor = {
        "provider": audit.provider,
        "model": audit.model,
        "agent_id": audit.agent_id,
        "prompt_version": audit.prompt_version,
        "prompt_sha256": audit.prompt_sha256,
        "schema_version": audit.schema_version,
        "segment_fingerprint": audit.segment_fingerprint,
        "entity_mentions": list(candidate.entity_mentions),
        "temporal_expression": candidate.temporal_expression,
        "ambiguity_flags": list(candidate.ambiguity_flags),
        "possible_supersedes": list(candidate.possible_supersedes),
        "policy_action": decision_action.value,
        "sensitivity": sensitivity,
    }
    if candidate.kind is CandidateKind.MEMORY:
        return {
            "statement": candidate.statement,
            "memory_type": None,
            "confidence": candidate.confidence,
            "impact": impact.value,
            "entity_ids": [],
            "extractor": extractor,
        }
    if candidate.kind is CandidateKind.ENTITY:
        display_name = (
            candidate.entity_mentions[0]
            if len(candidate.entity_mentions) == 1
            else None
        )
        return {
            "display_name": display_name,
            "normalized_name": (
                normalize_alias(display_name) if display_name is not None else None
            ),
            "entity_type": None,
            "aliases": [],
            "linked_notes": [],
            "extractor": extractor,
        }
    if candidate.kind is CandidateKind.RELATION:
        return {
            "statement": candidate.statement,
            "from_entity_id": None,
            "predicate": None,
            "to_entity_id": None,
            "literal": None,
            "confidence": candidate.confidence,
            "impact": impact.value,
            "extractor": extractor,
        }
    if candidate.kind is CandidateKind.COMMITMENT:
        source_at = _source_timestamp(segment, candidate)
        if source_at is None:
            due_date = due_time = None
            due_precision = DuePrecision.AMBIGUOUS
        else:
            resolution = resolve_due(
                candidate.statement,
                source_at=source_at,
                timezone=timezone_name,
            )
            due_date = resolution.due_date
            due_time = resolution.due_time
            due_precision = resolution.due_precision
        return {
            "statement": candidate.statement,
            "actor_entity_id": None,
            "confidence": candidate.confidence,
            "impact": impact.value,
            "timezone": timezone_name,
            "due_date": due_date,
            "due_time": due_time,
            "due_precision": due_precision.value,
            "target_entity_ids": [],
            "notify": False,
            "extractor": extractor,
        }
    return {
        "statement": candidate.statement,
        "confidence": candidate.confidence,
        "impact": impact.value,
        "entity_mentions": list(candidate.entity_mentions),
        "temporal_expression": candidate.temporal_expression,
        "ambiguity_flags": list(candidate.ambiguity_flags),
        "possible_supersedes": list(candidate.possible_supersedes),
        "extractor": extractor,
    }


def stage_inbox_source(
    config: NexusConfig,
    llm: object,
    *,
    relative_path: str,
    confirmed_sha256: str,
    conversation_id: str | None = None,
    max_segments: int = 20,
    max_segment_chars: int = 12_000,
    max_attempts: int = 2,
) -> StagedIngestReport:
    """Extract one exact source into private review state without Vault writes."""
    prepared = _prepare_exact_source(
        config,
        relative_path=relative_path,
        confirmed_sha256=confirmed_sha256,
        conversation_id=conversation_id,
        max_segments=max_segments,
        max_segment_chars=max_segment_chars,
    )
    service = ExtractionService(llm, max_attempts=max_attempts)
    outcomes = tuple(service.extract(segment) for segment in prepared.segments)
    conversation = prepared.parsed.conversations[prepared.conversation_index]
    state_store = SourceStateStore(config.data_path / "state/sources-v1.json")
    review_store = ReviewStore(config.data_path)
    existing_fingerprints = {
        item.candidate_fingerprint for item in review_store.list()
    }

    quarantine_source = any(
        evaluate_policy(
            _policy_input(candidate, segment, timezone_name=config.timezone)
        ).action
        is PolicyAction.QUARANTINE
        for segment, outcome in zip(prepared.segments, outcomes, strict=True)
        for candidate in outcome.result.candidates
    )
    raw_store = RawStore(config.data_path)
    destination_root = config.data_path / ("quarantine" if quarantine_source else "raw")
    raw_destination = (
        destination_root
        / prepared.source.content_sha256[:2]
        / f"{prepared.source.content_sha256}{prepared.source.suffix}"
    )
    raw_preexisting = raw_destination.exists()
    if quarantine_source:
        raw_store.quarantine(prepared.source)
        raw_disposition = "quarantine"
    else:
        raw_store.archive(prepared.source)
        raw_disposition = "archive"

    observation = state_store.observe(
        source_type=prepared.parsed.source_type,
        external_id=conversation.external_conversation_id,
        content_sha256=conversation.content_sha256,
    )
    created = reused = discarded = quarantined = 0
    for segment, outcome in zip(prepared.segments, outcomes, strict=True):
        for candidate in outcome.result.candidates:
            decision = evaluate_policy(
                _policy_input(candidate, segment, timezone_name=config.timezone)
            )
            if decision.action is PolicyAction.DISCARD:
                discarded += 1
                continue
            if decision.action is PolicyAction.QUARANTINE:
                quarantined += 1
                continue
            reasons = list(decision.reason_codes)
            if decision.action is PolicyAction.WOULD_PUBLISH:
                reasons.append("auto_publish_disabled")
            if candidate.kind is CandidateKind.MEMORY:
                reasons.append("memory_type_required")
            if candidate.kind is CandidateKind.ENTITY:
                reasons.append("entity_type_required")
            if candidate.kind is CandidateKind.RELATION:
                reasons.append("relation_fields_required")
            item = create_review_item(
                candidate_kind=candidate.kind.value,
                candidate=_review_candidate(
                    candidate,
                    outcome,
                    decision.action,
                    impact=decision.impact,
                    sensitivity=decision.sensitivity.value,
                    segment=segment,
                    timezone_name=config.timezone,
                ),
                reason_codes=reasons,
                source_refs=(
                    _source_ref(observation.source_id, segment, candidate),
                ),
            )
            fingerprint = item.candidate_fingerprint
            review_store.enqueue(item)
            if fingerprint in existing_fingerprints:
                reused += 1
            else:
                existing_fingerprints.add(fingerprint)
                created += 1

    return StagedIngestReport(
        source_type=prepared.parsed.source_type.value,
        adapter=f"{prepared.parsed.adapter_name}@{prepared.parsed.adapter_version}",
        source_sha256=prepared.source.content_sha256,
        conversations=1,
        messages=len(conversation.messages),
        segments=len(prepared.segments),
        candidates=sum(len(outcome.result.candidates) for outcome in outcomes),
        review_items_created=created,
        review_items_reused=reused,
        discarded=discarded,
        quarantined=quarantined,
        source_revision=observation.revision,
        duplicate_source=observation.duplicate,
        raw_disposition=raw_disposition,
        writes_performed=(
            not raw_preexisting or not observation.duplicate or created > 0
        ),
    )


def build_source_record(
    *,
    parsed: ParsedSource,
    conversation_index: int,
    discovered: DiscoveredSource,
    observation: SourceObservation,
    raw_locator: str,
    retention_days: int,
    now: datetime | None = None,
) -> Source:
    """Build canonical Source metadata after an explicit archive/state transaction."""
    conversation = parsed.conversations[conversation_index]
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    retained_until = (instant.date() + timedelta(days=retention_days)).isoformat()
    return Source(
        id=observation.source_id,
        source_type=parsed.source_type,
        external_id=conversation.external_conversation_id,
        revision=observation.revision,
        content_sha256=conversation.content_sha256,
        message_count=len(conversation.messages),
        source_started_at=conversation.started_at,
        source_ended_at=conversation.ended_at,
        ingested_at=instant.isoformat(timespec="seconds"),
        original_name=discovered.path.name,
        locator=raw_locator,
        parser={"name": parsed.adapter_name, "version": parsed.adapter_version},
        retained_until=retained_until,
        availability=SourceAvailability.AVAILABLE,
    )
