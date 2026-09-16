from __future__ import annotations

import unittest

from nexus.normalize import NormalizedConversation, NormalizedMessage
from nexus.segmenter import segment_conversation


def message(
    identifier: str, role: str, content: str, *, extractable: bool | None = None
):
    built = NormalizedMessage.build(
        message_id=identifier,
        role=role,
        content=content,
        source_locator=f"test#message={identifier}",
    )
    if extractable is None or built.include_for_extraction == extractable:
        return built
    return NormalizedMessage(
        message_id=built.message_id,
        role=built.role,
        content_text=built.content_text,
        content_sha256=built.content_sha256,
        source_locator=built.source_locator,
        include_for_extraction=extractable,
    )


def conversation(messages: tuple[NormalizedMessage, ...]) -> NormalizedConversation:
    return NormalizedConversation(
        external_conversation_id="conversation-1",
        title="Synthetic",
        participants=("assistant", "user"),
        messages=messages,
        source_locator="test:conversation-1",
    )


class SegmenterTests(unittest.TestCase):
    def test_preserves_turns_and_overlaps_previous_turn(self) -> None:
        source = conversation(
            (
                message("u1", "user", "u" * 6),
                message("a1", "assistant", "a" * 6),
                message("u2", "user", "v" * 6),
                message("a2", "assistant", "b" * 6),
                message("u3", "user", "w" * 6),
                message("a3", "assistant", "c" * 6),
            )
        )

        segments = segment_conversation(source, max_chars=25, overlap_turns=1)

        self.assertEqual(2, len(segments))
        self.assertEqual(("u1", "a1", "u2", "a2"), segments[0].span_ids)
        self.assertEqual(("u2", "a2", "u3", "a3"), segments[1].span_ids)
        self.assertEqual(("u2", "a2"), segments[1].overlap_span_ids)
        self.assertEqual(
            segments,
            segment_conversation(source, max_chars=25, overlap_turns=1),
        )

    def test_system_and_tool_messages_are_not_sent_for_extraction(self) -> None:
        source = conversation(
            (
                message("s1", "system", "private system context"),
                message("u1", "user", "real user text"),
                message("t1", "tool", "tool output"),
                message("a1", "assistant", "answer"),
            )
        )

        segment = segment_conversation(source)[0]

        self.assertEqual(("u1", "a1"), segment.span_ids)

    def test_single_oversized_turn_is_preserved_and_flagged(self) -> None:
        source = conversation((message("u1", "user", "x" * 100),))

        segment = segment_conversation(source, max_chars=10)[0]

        self.assertTrue(segment.oversized_turn)
        self.assertEqual(("u1",), segment.span_ids)


if __name__ == "__main__":
    unittest.main()
