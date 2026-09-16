"""Read-only Phase 2 ingestion planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .config import NexusConfig
from .contracts import Source, SourceAvailability
from .errors import ParseError, SourceError
from .raw_store import DiscoveredSource, discover_inbox, read_discovered
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


ADAPTERS: tuple[SourceAdapter, ...] = (ChatGPTAdapter(), HermesAdapter(), ManualAdapter())


def _parse(source: DiscoveredSource) -> ParsedSource:
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
            parsed = _parse(source)
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
