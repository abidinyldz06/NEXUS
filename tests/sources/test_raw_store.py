from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from nexus.errors import UnsafeSourceError
from nexus.raw_store import RawStore, discover_inbox


class RawStoreTests(unittest.TestCase):
    def _stable_file(self, root: Path, name: str, payload: bytes) -> Path:
        path = root / name
        path.write_bytes(payload)
        old = time.time() - 60
        os.utime(path, (old, old))
        return path

    def test_discovery_rejects_symlink_oversize_and_format_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = self._stable_file(root, "good.md", b"safe note")
            (root / "link.md").symlink_to(target)
            self._stable_file(root, "large.md", b"x" * 11)
            self._stable_file(root, "wrong.json", b"not json")

            report = discover_inbox(root, max_source_bytes=10, stable_seconds=1)

        self.assertEqual(["good.md"], [item.relative_path for item in report.accepted])
        reasons = {item.relative_path: item.reason for item in report.rejected}
        self.assertEqual("symlink_rejected", reasons["link.md"])
        self.assertEqual("oversize", reasons["large.md"])
        self.assertEqual("format_mismatch", reasons["wrong.json"])

    def test_archive_is_content_addressed_private_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            source_path = self._stable_file(inbox, "note.md", b"synthetic note")
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            store = RawStore(root / "private")

            first = store.archive(discovered)
            second = store.archive(discovered)

            self.assertEqual(first, second)
            self.assertTrue(source_path.exists(), "archive must not delete the Inbox source")
            self.assertEqual(0o600, first.stat().st_mode & 0o777)

    def test_archive_rejects_source_changed_after_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            source_path = self._stable_file(inbox, "note.md", b"first")
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            source_path.write_bytes(b"second")

            with self.assertRaises(UnsafeSourceError):
                RawStore(root / "private").archive(discovered)

    def test_quarantine_is_separate_from_raw_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            self._stable_file(inbox, "bad.md", b"untrusted synthetic content")
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]

            destination = RawStore(root / "private").quarantine(discovered)

            self.assertIn("quarantine", destination.parts)
            self.assertNotIn("raw", destination.parts)
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)


if __name__ == "__main__":
    unittest.main()
