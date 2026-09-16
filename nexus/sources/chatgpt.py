"""Adapter for the common ChatGPT conversations.json export shape.

Synthetic fixtures cover this implementation. Real-export acceptance remains a
separate Phase 0/2 gate because OpenAI may evolve the export structure.
"""

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


def _chatgpt_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return "" if content is None else str(content)
    parts = content.get("parts")
    if isinstance(parts, list):
        rendered: list[str] = []
        for part in parts:
            if isinstance(part, str):
                rendered.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    rendered.append(text)
        return "\n".join(rendered)
    text = content.get("text")
    return text if isinstance(text, str) else ""


def _current_branch(
    mapping: dict[str, Any], current_node: object
) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(current_node, str) and current_node in mapping:
        branch: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        node_id: str | None = current_node
        while node_id and node_id not in seen:
            seen.add(node_id)
            node = mapping.get(node_id)
            if not isinstance(node, dict):
                break
            branch.append((node_id, node))
            parent = node.get("parent")
            node_id = parent if isinstance(parent, str) else None
        branch.reverse()
        return branch
    return [(str(node_id), node) for node_id, node in mapping.items() if isinstance(node, dict)]


class ChatGPTAdapter:
    name = "chatgpt-conversations-json"
    version = "1-synthetic-validated"
    source_type = SourceType.CHATGPT

    def supports(self, path: Path, payload_prefix: bytes) -> bool:
        return path.suffix.lower() == ".json"

    def parse_bytes(self, payload: bytes, *, original_name: str) -> ParsedSource:
        try:
            root = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParseError("invalid ChatGPT conversations JSON") from exc
        if isinstance(root, dict) and isinstance(root.get("conversations"), list):
            raw_conversations = root["conversations"]
        elif isinstance(root, list):
            raw_conversations = root
        elif isinstance(root, dict) and "mapping" in root:
            raw_conversations = [root]
        else:
            raise ParseError("ChatGPT export must be a conversation object or array")
        if not raw_conversations:
            raise ParseError("ChatGPT export contains no conversations")

        conversations = tuple(
            self._normalize_conversation(require_mapping(item, label="conversation"), index)
            for index, item in enumerate(raw_conversations)
        )
        return ParsedSource(
            source_type=self.source_type,
            adapter_name=self.name,
            adapter_version=self.version,
            original_name=Path(original_name).name,
            conversations=conversations,
        )

    def _normalize_conversation(
        self, conversation: dict[str, Any], index: int
    ) -> NormalizedConversation:
        conversation_id = str(
            conversation.get("id") or conversation.get("conversation_id") or ""
        ).strip()
        if not conversation_id:
            raise ParseError(f"ChatGPT conversation {index + 1} has no id")
        mapping = conversation.get("mapping")
        if not isinstance(mapping, dict):
            raise ParseError(f"ChatGPT conversation {conversation_id} has no mapping")
        locator = f"chatgpt:conversation:{conversation_id}"
        messages: list[NormalizedMessage] = []
        for node_id, node in _current_branch(mapping, conversation.get("current_node")):
            raw = node.get("message")
            if raw is None:
                continue
            if not isinstance(raw, dict):
                raise ParseError(f"ChatGPT conversation {conversation_id} has an invalid message")
            author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
            role = author.get("role", "unknown")
            content = normalize_text(_chatgpt_content(raw.get("content")))
            raw_id = raw.get("id") or node_id
            if not raw_id:
                raw_id = fallback_message_id(
                    source_identity=conversation_id,
                    role=str(role),
                    created_at=str(raw.get("create_time") or ""),
                    content_sha256=sha256_bytes(content.encode("utf-8")),
                )
            messages.append(
                NormalizedMessage.build(
                    message_id=str(raw_id),
                    parent_message_id=node.get("parent"),
                    role=role,
                    author_id=author.get("name"),
                    created_at=raw.get("create_time"),
                    content=content,
                    source_locator=f"{locator}#message={raw_id}",
                )
            )
        normalized = tuple(messages)
        started_at, ended_at = conversation_bounds(normalized)
        return NormalizedConversation(
            external_conversation_id=conversation_id,
            title=normalize_text(
                conversation.get("title") or f"ChatGPT conversation {conversation_id}"
            ),
            participants=tuple(sorted({item.role for item in normalized})),
            messages=normalized,
            source_locator=locator,
            started_at=started_at,
            ended_at=ended_at,
        )
