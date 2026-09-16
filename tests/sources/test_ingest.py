from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nexus.ingest import build_source_record
from nexus.raw_store import discover_inbox
from nexus.sources import ManualAdapter
from nexus.state import SourceStateStore


class IngestMetadataTests(unittest.TestCase):
    def test_normalized_conversation_builds_versioned_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Sentetik tercih", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            parsed = ManualAdapter().parse_bytes(note.read_bytes(), original_name=note.name)
            conversation = parsed.conversations[0]
            observation = SourceStateStore(root / "state" / "sources.json").observe(
                source_type=parsed.source_type,
                external_id=conversation.external_conversation_id,
                content_sha256=conversation.content_sha256,
            )

            source = build_source_record(
                parsed=parsed,
                conversation_index=0,
                discovered=discovered,
                observation=observation,
                raw_locator="raw/ab/hash.md",
                retention_days=90,
                now=datetime(2026, 9, 16, tzinfo=timezone.utc),
            )

        self.assertEqual(observation.source_id, source.id)
        self.assertEqual(1, source.revision)
        self.assertEqual("note.md", source.original_name)
        self.assertEqual("2026-12-15", source.retained_until)
        self.assertEqual(conversation.content_sha256, source.content_sha256)


if __name__ == "__main__":
    unittest.main()
