"""Write-free Phase 2 ingestion planning and exact-source shadow extraction."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from .config import NexusConfig
from .contracts import Source, SourceAvailability
from .errors import ParseError, SourceError
from .extraction.service import PROMPT_VERSION, ExtractionService
from .raw_store import DiscoveredSource, discover_inbox, read_discovered
from .segmenter import segment_conversation
from .sources import ChatGPTAdapter, HermesAdapter, ManualAdapter, ParsedSource, SourceAdapter
from .state import SourceObservation


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
        conversations = parsed.conversations
    else:
        conversations = tuple(
            item
            for item in parsed.conversations
            if item.external_conversation_id == conversation_id
        )
        if len(conversations) != 1:
            raise SourceError("selected conversation was not found uniquely")
    segments = tuple(
        segment
        for conversation in conversations
        for segment in segment_conversation(conversation, max_chars=max_segment_chars)
    )
    if not segments:
        raise SourceError("selected source contains no extractable segments")
    if len(segments) > max_segments:
        raise SourceError("selected conversation exceeds max-segments before model execution")

    service = ExtractionService(llm, max_attempts=max_attempts)
    kind_counts: Counter[str] = Counter()
    audits = []
    segment_count = 0
    candidate_count = 0
    warning_count = 0
    for segment in segments:
        outcome = service.extract(segment)
        audits.append(outcome.audit)
        segment_count += 1
        candidate_count += len(outcome.result.candidates)
        warning_count += len(outcome.result.warnings)
        kind_counts.update(item.kind.value for item in outcome.result.candidates)

    return ShadowIngestReport(
        source_type=parsed.source_type.value,
        adapter=f"{parsed.adapter_name}@{parsed.adapter_version}",
        source_sha256=source.content_sha256,
        conversations=len(conversations),
        messages=sum(len(item.messages) for item in conversations),
        segments=segment_count,
        segment_limit=max_segments,
        candidates=candidate_count,
        candidate_kinds=dict(sorted(kind_counts.items())),
        warnings=warning_count,
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
