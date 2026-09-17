"""Safe, deterministic Markdown rendering for canonical NEXUS records."""

from __future__ import annotations

import base64
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..contracts import Commitment, Entity, Memory, Relation, ReviewItem, Source, SourceRef
from ..errors import VaultError
from ..ids import IdPrefix, is_nexus_id
from ..serialization import to_primitive

_PAYLOAD_RE = re.compile(r"<!-- nexus-record-v1:([A-Za-z0-9_-]+) -->")


@dataclass(frozen=True, slots=True)
class RecordDescriptor:
    kind: str
    record_id: str
    status: str
    title: str
    primary_text: str
    source_refs: tuple[SourceRef, ...]


def _descriptor(record: object) -> RecordDescriptor:
    if isinstance(record, Memory):
        return RecordDescriptor(
            "memory",
            record.id,
            record.status.value,
            f"NEXUS Memory — {record.type.value}",
            record.summary,
            record.source_refs,
        )
    if isinstance(record, Entity):
        return RecordDescriptor(
            "entity",
            record.id,
            "active",
            f"NEXUS Entity — {record.type.value}",
            record.display_name,
            record.source_refs,
        )
    if isinstance(record, Relation):
        return RecordDescriptor(
            "relation",
            record.id,
            record.status.value,
            "NEXUS Relation",
            record.predicate,
            record.source_refs,
        )
    if isinstance(record, Commitment):
        return RecordDescriptor(
            "commitment",
            record.id,
            record.status.value,
            "NEXUS Commitment",
            record.summary,
            record.source_refs,
        )
    if isinstance(record, Source):
        return RecordDescriptor(
            "source",
            record.id,
            record.availability.value,
            "NEXUS Source",
            record.original_name or record.locator or record.id,
            (),
        )
    if isinstance(record, ReviewItem):
        return RecordDescriptor(
            "review",
            record.id,
            record.status.value,
            "NEXUS Review",
            record.candidate_kind,
            record.source_refs,
        )
    raise VaultError(f"unsupported canonical record type: {type(record).__name__}")


def _encoded_payload(record: object) -> str:
    raw = json.dumps(
        to_primitive(record),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def render_safe_pre(value: str) -> str:
    escaped = html.escape(value, quote=True)
    for character, entity in (
        ("!", "&#33;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("`", "&#96;"),
    ):
        escaped = escaped.replace(character, entity)
    return f"<pre>{escaped}</pre>"


def render_record(record: object, *, run_id: str, written_at: str) -> str:
    if not is_nexus_id(run_id, IdPrefix.RUN):
        raise VaultError("run_id must be a run_ NEXUS id")
    try:
        parsed_written_at = datetime.fromisoformat(written_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VaultError("written_at must be an ISO 8601 datetime") from exc
    if parsed_written_at.tzinfo is None:
        raise VaultError("written_at must include a timezone offset")
    descriptor = _descriptor(record)
    payload = _encoded_payload(record)
    lines = [
        "---",
        f"nexus_id: {descriptor.record_id}",
        f"record_kind: {descriptor.kind}",
        f"schema_version: {getattr(record, 'schema_version', 1)}",
        f"status: {descriptor.status}",
        f"run_id: {run_id}",
        f"written_at: {written_at}",
        "managed_by: nexus",
        "---",
        "",
        f"# {descriptor.title}",
        "",
        render_safe_pre(descriptor.primary_text),
        "",
        "## Provenance",
        "",
    ]
    if not descriptor.source_refs:
        lines.append("This source record is the provenance root.")
    for ref in descriptor.source_refs:
        lines.extend(
            [
                f"- Source: `{ref.source_id}`",
                f"  - Conversation: `{ref.conversation_id}`",
                f"  - Spans: {', '.join(f'`{item}`' for item in ref.span_ids)}",
                f"  - Span SHA-256: `{ref.span_sha256}`",
            ]
        )
        if ref.excerpt:
            lines.extend(["  - Evidence:", render_safe_pre(ref.excerpt)])
    lines.extend(["", f"<!-- nexus-record-v1:{payload} -->", ""])
    return "\n".join(lines)


def extract_record_payload(markdown: str) -> dict[str, Any]:
    match = _PAYLOAD_RE.search(markdown)
    if match is None:
        raise VaultError("canonical record payload marker is missing")
    encoded = match.group(1)
    padding = "=" * (-len(encoded) % 4)
    try:
        raw = base64.urlsafe_b64decode(encoded + padding)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise VaultError("canonical record payload is invalid") from exc
    if not isinstance(payload, dict):
        raise VaultError("canonical record payload must be an object")
    return payload
