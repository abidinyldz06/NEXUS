"""Provider-neutral conversation normalization."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from .errors import ParseError


NORMALIZATION_VERSION = "nexus-normalize-v1"


def normalize_text(value: object) -> str:
    """Normalize Unicode/newlines while preserving meaningful whitespace."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def normalize_role(value: object) -> str:
    role = str(value or "unknown").strip().lower()
    aliases = {"human": "user", "ai": "assistant", "function": "tool"}
    return aliases.get(role, role) if role else "unknown"


def normalize_timestamp(value: object) -> str | None:
    """Return an aware UTC ISO-8601 timestamp or None."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 10_000_000_000:
                numeric /= 1000
            parsed = datetime.fromtimestamp(numeric, tz=timezone.utc)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            parsed = parsed.astimezone(timezone.utc)
        else:
            raise ValueError
    except (OverflowError, OSError, ValueError) as exc:
        raise ParseError(f"invalid timestamp: {value!r}") from exc
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    message_id: str
    role: str
    content_text: str
    content_sha256: str
    source_locator: str
    parent_message_id: str | None = None
    author_id: str | None = None
    created_at: str | None = None
    include_for_extraction: bool = True

    @classmethod
    def build(
        cls,
        *,
        message_id: str,
        role: object,
        content: object,
        source_locator: str,
        parent_message_id: str | None = None,
        author_id: str | None = None,
        created_at: object = None,
    ) -> "NormalizedMessage":
        text = normalize_text(content)
        normalized_role = normalize_role(role)
        return cls(
            message_id=str(message_id),
            parent_message_id=str(parent_message_id) if parent_message_id else None,
            role=normalized_role,
            author_id=str(author_id) if author_id else None,
            created_at=normalize_timestamp(created_at),
            content_text=text,
            content_sha256=sha256_text(text),
            source_locator=source_locator,
            include_for_extraction=normalized_role in {"user", "assistant"},
        )


@dataclass(frozen=True, slots=True)
class NormalizedConversation:
    external_conversation_id: str
    title: str
    participants: tuple[str, ...]
    messages: tuple[NormalizedMessage, ...]
    source_locator: str
    started_at: str | None = None
    ended_at: str | None = None

    @property
    def content_sha256(self) -> str:
        payload = [
            {
                "id": item.message_id,
                "parent": item.parent_message_id,
                "role": item.role,
                "created_at": item.created_at,
                "content_sha256": item.content_sha256,
            }
            for item in self.messages
        ]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256_text(encoded)


def conversation_bounds(messages: tuple[NormalizedMessage, ...]) -> tuple[str | None, str | None]:
    timestamps = sorted(item.created_at for item in messages if item.created_at is not None)
    return (timestamps[0], timestamps[-1]) if timestamps else (None, None)


def require_mapping(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ParseError(f"{label} must be a JSON object")
    return value
