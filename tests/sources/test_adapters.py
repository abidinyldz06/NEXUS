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

    def test_chatgpt_html_wrapper_is_decoded_without_executing_script(self) -> None:
        path = FIXTURES / "chatgpt" / "conversations.synthetic.json"
        html = (
            "<!doctype html><html><body><script>var jsonData = "
            + path.read_text(encoding="utf-8")
            + "; globalThis.mustNotRun = true;</script></body></html>"
        ).encode()
        adapter = ChatGPTAdapter()

        self.assertTrue(adapter.supports(Path("chat.html"), html[:16_384]))
        parsed = adapter.parse_bytes(html, original_name="chat.html")

        self.assertEqual("chatgpt", parsed.source_type.value)
        self.assertEqual("2-json-html", parsed.adapter_version)
        self.assertEqual(1, len(parsed.conversations))
        self.assertEqual(2, parsed.message_count)
        self.assertEqual("chat-conv-1", parsed.conversations[0].external_conversation_id)

    def test_chatgpt_adapter_does_not_claim_unrelated_html(self) -> None:
        payload = b"<!doctype html><html><body>Manual note</body></html>"
        self.assertFalse(ChatGPTAdapter().supports(Path("note.html"), payload))

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
