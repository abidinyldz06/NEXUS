from __future__ import annotations

import unittest
from pathlib import Path

from nexus.errors import ParseError
from nexus.sources import ChatGPTAdapter, HermesAdapter, ManualAdapter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class AdapterTests(unittest.TestCase):
    def test_chatgpt_synthetic_fixture_preserves_current_branch(self) -> None:
        path = FIXTURES / "chatgpt" / "conversations.synthetic.json"
        parsed = ChatGPTAdapter().parse_bytes(path.read_bytes(), original_name=path.name)

        self.assertEqual("chatgpt", parsed.source_type.value)
        self.assertEqual(1, len(parsed.conversations))
        conversation = parsed.conversations[0]
        self.assertEqual("chat-conv-1", conversation.external_conversation_id)
        self.assertEqual(
            ["chat-msg-1", "chat-msg-2"],
            [item.message_id for item in conversation.messages],
        )
        self.assertTrue(all(item.content_sha256 for item in conversation.messages))

    def test_hermes_official_jsonl_shape_keeps_metadata_roles_out_of_extraction(self) -> None:
        path = FIXTURES / "hermes" / "sessions.synthetic.jsonl"
        parsed = HermesAdapter().parse_bytes(path.read_bytes(), original_name=path.name)

        conversation = parsed.conversations[0]
        self.assertEqual("hermes-session-1", conversation.external_conversation_id)
        self.assertEqual(4, len(conversation.messages))
        extractable = [item.role for item in conversation.messages if item.include_for_extraction]
        self.assertEqual(["user", "assistant"], extractable)

    def test_manual_html_is_parsed_without_script_or_style_content(self) -> None:
        path = FIXTURES / "manual" / "note.synthetic.html"
        parsed = ManualAdapter().parse_bytes(path.read_bytes(), original_name=path.name)
        text = parsed.conversations[0].messages[0].content_text

        self.assertIn("Kısa yanıtları", text)
        self.assertNotIn("syntheticFixtureMustNotRender", text)
        self.assertNotIn("display: none", text)

    def test_malformed_exports_fail_closed(self) -> None:
        with self.assertRaises(ParseError):
            ChatGPTAdapter().parse_bytes(b'{"unexpected": true}', original_name="bad.json")
        with self.assertRaises(ParseError):
            HermesAdapter().parse_bytes(b'{not-json}\n', original_name="bad.jsonl")


if __name__ == "__main__":
    unittest.main()
