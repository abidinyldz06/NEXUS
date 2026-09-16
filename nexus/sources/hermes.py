"""Adapter for Hermes's official full-session JSONL export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import SourceType
from ..errors import ParseError
from ..fingerprints import fallback_message_id, sha256_bytes
from ..normalize import (
    NormalizedConversation,
    NormalizedMessage,
    conversation_bounds,
    normalize_text,
    require_mapping,
)
from .base import ParsedSource


def _content_text(value: Any) -> str:
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                candidate = part.get("text", part.get("content", ""))
                if isinstance(candidate, str):
                    parts.append(candidate)
                else:
                    parts.append(json.dumps(candidate, ensure_ascii=False, sort_keys=True))
            else:
                parts.append(str(part))
        return "\n".join(parts)
    if isinstance(value, dict):
        candidate = value.get("text", value.get("content"))
        if isinstance(candidate, str):
            return candidate
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else str(value)


class HermesAdapter:
    name = "hermes-jsonl"
    version = "1"
    source_type = SourceType.HERMES

    def supports(self, path: Path, payload_prefix: bytes) -> bool:
        return path.suffix.lower() == ".jsonl"

    def parse_bytes(self, payload: bytes, *, original_name: str) -> ParsedSource:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ParseError("Hermes export must be UTF-8 JSONL") from exc
        sessions: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                sessions.append(require_mapping(json.loads(line), label=f"line {line_number}"))
            except json.JSONDecodeError as exc:
                raise ParseError(f"invalid Hermes JSONL at line {line_number}") from exc
        if not sessions:
            raise ParseError("Hermes export contains no sessions")

        conversations = tuple(
            self._normalize_session(item, index) for index, item in enumerate(sessions)
        )
        return ParsedSource(
            source_type=self.source_type,
            adapter_name=self.name,
            adapter_version=self.version,
            original_name=Path(original_name).name,
            conversations=conversations,
        )

    def _normalize_session(self, session: dict[str, Any], index: int) -> NormalizedConversation:
        session_id = str(session.get("id") or session.get("session_id") or "").strip()
        if not session_id:
            raise ParseError(f"Hermes session {index + 1} has no id")
        locator = f"hermes:session:{session_id}"
        raw_messages = session.get("messages")
        if not isinstance(raw_messages, list):
            raise ParseError(f"Hermes session {session_id} has no messages array")

        messages: list[NormalizedMessage] = []
        for message_index, raw in enumerate(raw_messages):
            if not isinstance(raw, dict):
                raise ParseError(
                    f"Hermes session {session_id} message {message_index + 1} is invalid"
                )
            content = normalize_text(_content_text(raw.get("content")))
            role = raw.get("role", "unknown")
            raw_id = raw.get("id") or raw.get("message_id") or raw.get("platform_message_id")
            if raw_id is None:
                raw_id = fallback_message_id(
                    source_identity=session_id,
                    role=str(role),
                    created_at=str(raw.get("timestamp") or ""),
                    content_sha256=sha256_bytes(content.encode("utf-8")),
                )
            messages.append(
                NormalizedMessage.build(
                    message_id=str(raw_id),
                    parent_message_id=raw.get("parent_id") or raw.get("parent_message_id"),
                    role=role,
                    author_id=raw.get("author_id") or raw.get("name") or raw.get("tool_name"),
                    created_at=raw.get("timestamp") or raw.get("created_at"),
                    content=content,
                    source_locator=f"{locator}#message={raw_id}",
                )
            )
        normalized = tuple(messages)
        started_at, ended_at = conversation_bounds(normalized)
        return NormalizedConversation(
            external_conversation_id=session_id,
            title=normalize_text(session.get("title") or f"Hermes session {session_id}"),
            participants=tuple(sorted({item.role for item in normalized})),
            messages=normalized,
            source_locator=locator,
            started_at=started_at,
            ended_at=ended_at,
        )
