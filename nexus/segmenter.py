"""Deterministic, turn-aware conversation segmentation."""

from __future__ import annotations

from dataclasses import dataclass

from .fingerprints import segment_fingerprint
from .normalize import NormalizedConversation, NormalizedMessage


SEGMENTER_VERSION = "nexus-segmenter-v1"


@dataclass(frozen=True, slots=True)
class ConversationSegment:
    conversation_id: str
    index: int
    messages: tuple[NormalizedMessage, ...]
    fingerprint: str
    overlap_span_ids: tuple[str, ...] = ()
    oversized_turn: bool = False

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
