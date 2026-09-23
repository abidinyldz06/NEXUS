"""Deterministic, turn-aware conversation segmentation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .fingerprints import segment_fingerprint
from .normalize import NormalizedConversation, NormalizedMessage, normalize_text


SEGMENTER_VERSION = "nexus-segmenter-v1"
SEGMENT_ID_SCHEMA_VERSION = "nexus-segment-schema-v2"
DEFAULT_TARGET_CHARS = 12_000
DEFAULT_MAX_MESSAGES = 12
_FIELD_SEPARATOR = "\x1f"
_PART_SEPARATOR = "\x1e"


@dataclass(frozen=True, slots=True)
class ConversationSegment:
    conversation_id: str
    index: int
    messages: tuple[NormalizedMessage, ...]
    fingerprint: str
    overlap_span_ids: tuple[str, ...] = ()
    oversized_turn: bool = False
    segment_id: str = ""
    start_message_index: int = 0
    end_message_index: int = 0
    schema_version: str = ""
    content_hash: str = ""
    split_fallback: bool = False

    @property
    def span_ids(self) -> tuple[str, ...]:
        return tuple(item.message_id for item in self.messages)

    @property
    def character_count(self) -> int:
        return sum(len(item.content_text) for item in self.messages)


def _extractable_turns(
    messages: tuple[NormalizedMessage, ...],
) -> list[tuple[NormalizedMessage, ...]]:
    turns: list[list[NormalizedMessage]] = []
    current: list[NormalizedMessage] = []
    for message in messages:
        if not message.include_for_extraction or not message.content_text:
            continue
        if message.role == "user" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    return [tuple(turn) for turn in turns]


def _turn_size(turn: tuple[NormalizedMessage, ...]) -> int:
    return sum(len(message.content_text) for message in turn)


def segment_conversation(
    conversation: NormalizedConversation,
    *,
    max_chars: int = 12_000,
    overlap_turns: int = 1,
) -> tuple[ConversationSegment, ...]:
    """Split on natural user-turn boundaries with deterministic overlap.

    A single oversized turn remains intact and is marked for review; silently
    truncating it would break exact source-span provenance.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_turns < 0:
        raise ValueError("overlap_turns cannot be negative")
    turns = _extractable_turns(conversation.messages)
    if not turns:
        return ()

    groups: list[tuple[tuple[NormalizedMessage, ...], tuple[str, ...], bool]] = []
    cursor = 0
    previous_primary: tuple[tuple[NormalizedMessage, ...], ...] = ()
    while cursor < len(turns):
        overlap = previous_primary[-overlap_turns:] if overlap_turns else ()
        selected: list[tuple[NormalizedMessage, ...]] = list(overlap)
        overlap_ids = tuple(message.message_id for turn in overlap for message in turn)
        size = sum(_turn_size(turn) for turn in selected)
        primary: list[tuple[NormalizedMessage, ...]] = []

        while cursor < len(turns):
            turn = turns[cursor]
            turn_size = _turn_size(turn)
            if primary and size + turn_size > max_chars:
                break
            if not primary and selected and size + turn_size > max_chars:
                selected = []
                overlap_ids = ()
                size = 0
            primary.append(turn)
            selected.append(turn)
            size += turn_size
            cursor += 1
            if size >= max_chars:
                break

        flat = tuple(message for turn in selected for message in turn)
        oversized = any(_turn_size(turn) > max_chars for turn in primary)
        groups.append((flat, overlap_ids, oversized))
        previous_primary = tuple(primary)

    return tuple(
        ConversationSegment(
            conversation_id=conversation.external_conversation_id,
            index=index,
            messages=messages,
            fingerprint=segment_fingerprint(messages, version=SEGMENTER_VERSION),
            overlap_span_ids=overlap_ids,
            oversized_turn=oversized,
        )
        for index, (messages, overlap_ids, oversized) in enumerate(groups, start=1)
    )


def normalize_for_segment_id(text: str) -> str:
    """Normalize text before it is hashed into a segment id.

    Newlines (``\\r\\n`` and ``\\r``) become ``\\n``. Trailing whitespace on
    each line is removed, then the whole string is stripped. Unicode form is
    NFC. Callers hash the UTF-8 encoding of this result. Message order stays
    the conversation order; texts are not re-sorted.
    """
    return normalize_text(text)


def normalized_content_hash(texts: tuple[str, ...] | list[str]) -> str:
    """Hash normalized parts in the given order."""
    payload = _PART_SEPARATOR.join(normalize_for_segment_id(text) for text in texts)
    return sha256(payload.encode("utf-8")).hexdigest()


def deterministic_segment_id(
    *,
    conversation_id: str,
    start_message_index: int,
    end_message_index: int,
    schema_version: str,
    part_index: int = 0,
) -> str:
    """Stable id for one conversation range, schema version and fallback part."""
    material = _FIELD_SEPARATOR.join(
        (
            conversation_id,
            str(start_message_index),
            str(end_message_index),
            schema_version,
            str(part_index),
        )
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _fallback_parts(text: str, target_chars: int) -> tuple[str, ...]:
    """Split one oversized message without dropping characters.

    Prefer a whitespace boundary inside the budget. If the window has no
    space, cut at the budget. Joining the parts restores the normalized text.
    """
    rest = normalize_for_segment_id(text)
    if not rest:
        return ()
    parts: list[str] = []
    while rest:
        if len(rest) <= target_chars:
            parts.append(rest)
            break
        window = rest[:target_chars]
        space = window.rfind(" ")
        cut = space if space > 0 else target_chars
        parts.append(rest[:cut])
        rest = rest[cut:]
    return tuple(parts)


def _segment_from_messages(
    conversation: NormalizedConversation,
    *,
    ordinal: int,
    indexed: tuple[tuple[int, NormalizedMessage], ...],
    texts: tuple[str, ...],
    schema_version: str,
    split_fallback: bool,
    part_index: int = 0,
) -> ConversationSegment:
    start = indexed[0][0]
    end = indexed[-1][0]
    content_hash = normalized_content_hash(texts)
    messages = tuple(item[1] for item in indexed)
    return ConversationSegment(
        conversation_id=conversation.external_conversation_id,
        index=ordinal,
        messages=messages,
        fingerprint=segment_fingerprint(messages, version=SEGMENTER_VERSION),
        segment_id=deterministic_segment_id(
            conversation_id=conversation.external_conversation_id,
            start_message_index=start,
            end_message_index=end,
            schema_version=schema_version,
            part_index=part_index,
        ),
        start_message_index=start,
        end_message_index=end,
        schema_version=schema_version,
        content_hash=content_hash,
        split_fallback=split_fallback,
        oversized_turn=split_fallback,
    )


def segment_conversation_v2(
    conversation: NormalizedConversation,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    schema_version: str = SEGMENT_ID_SCHEMA_VERSION,
) -> tuple[ConversationSegment, ...]:
    """Pack extractable messages on message boundaries.

    ``target_chars`` is a character budget, not a token count. ``max_messages``
    caps packed turns so a 54-message blob cannot stay one 90s helper call.
    A turn stays together while the next message still fits both budgets. A
    single message that exceeds the character budget uses
    :func:`_fallback_parts`. Flag-off callers keep using
    :func:`segment_conversation` and v1 fingerprints.
    """
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    if max_messages <= 0:
        raise ValueError("max_messages must be positive")
    indexed = [
        (index, message)
        for index, message in enumerate(conversation.messages)
        if message.include_for_extraction and message.content_text
    ]
    if not indexed:
        return ()

    built: list[ConversationSegment] = []

    def add_group(group: list[tuple[int, NormalizedMessage]], *, fallback: bool) -> None:
        texts = tuple(message.content_text for _, message in group)
        built.append(
            _segment_from_messages(
                conversation,
                ordinal=len(built) + 1,
                indexed=tuple(group),
                texts=texts,
                schema_version=schema_version,
                split_fallback=fallback,
            )
        )

    current: list[tuple[int, NormalizedMessage]] = []
    size = 0
    for index, message in indexed:
        if len(normalize_for_segment_id(message.content_text)) > target_chars:
            if current:
                add_group(current, fallback=False)
                current = []
                size = 0
            for part_index, part in enumerate(_fallback_parts(message.content_text, target_chars)):
                built.append(
                    _segment_from_messages(
                        conversation,
                        ordinal=len(built) + 1,
                        indexed=((index, message),),
                        texts=(part,),
                        schema_version=schema_version,
                        split_fallback=True,
                        part_index=part_index,
                    )
                )
            continue
        message_size = len(normalize_for_segment_id(message.content_text))
        if current and (
            size + message_size > target_chars or len(current) >= max_messages
        ):
            add_group(current, fallback=False)
            current = []
            size = 0
        current.append((index, message))
        size += message_size
    if current:
        add_group(current, fallback=False)
    return tuple(built)
