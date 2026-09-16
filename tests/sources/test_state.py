from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nexus.contracts import SourceType
from nexus.state import SourceStateStore


class SourceStateTests(unittest.TestCase):
    def test_repeated_source_is_one_logical_source_and_one_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SourceStateStore(Path(directory) / "state" / "sources.json")
            observations = [
                store.observe(
                    source_type=SourceType.HERMES,
                    external_id="session-1",
                    content_sha256="a" * 64,
                )
                for _ in range(3)
            ]

        self.assertEqual(1, len({item.source_id for item in observations}))
        self.assertEqual([1, 1, 1], [item.revision for item in observations])
        self.assertEqual([False, True, True], [item.duplicate for item in observations])

    def test_growing_conversation_increments_revision_without_changing_source_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "sources.json"
            first = SourceStateStore(state_path).observe(
                source_type=SourceType.CHATGPT,
                external_id="conversation-1",
                content_sha256="a" * 64,
            )
            second = SourceStateStore(state_path).observe(
                source_type=SourceType.CHATGPT,
                external_id="conversation-1",
                content_sha256="b" * 64,
            )

        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(2, second.revision)
        self.assertFalse(second.duplicate)


if __name__ == "__main__":
    unittest.main()
