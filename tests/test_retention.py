from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from nexus.config import NexusConfig
from nexus.contracts import SourceRef
from nexus.errors import RetentionError
from nexus.ids import IdPrefix, new_id
from nexus.retention import plan_retention
from nexus.review import ReviewStore, create_review_item


def _source_ref() -> SourceRef:
    return SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id="conversation-1",
        span_ids=("msg_1",),
        span_sha256=sha256(b"msg_1").hexdigest(),
    )


class RetentionTests(unittest.TestCase):
    def _config(self, data_path: Path) -> NexusConfig:
        return NexusConfig.from_mapping(
            {
                "data_path": str(data_path),
                "raw_retention_days": 90,
                "rejected_retention_days": 30,
            }
        )

    def test_dry_run_counts_expired_private_data_without_writing(self) -> None:
        now = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "private"
            raw = data_path / "raw" / "aa"
            quarantine = data_path / "quarantine" / "bb"
            raw.mkdir(parents=True)
            quarantine.mkdir(parents=True)
            old_raw = raw / "old.json"
            fresh_raw = raw / "fresh.json"
            old_quarantine = quarantine / "old.json"
            old_raw.write_bytes(b"old raw")
            fresh_raw.write_bytes(b"fresh raw")
            old_quarantine.write_bytes(b"old rejected")
            os.utime(old_raw, (now.timestamp() - 91 * 86400,) * 2)
            os.utime(fresh_raw, (now.timestamp() - 10 * 86400,) * 2)
            os.utime(old_quarantine, (now.timestamp() - 31 * 86400,) * 2)
            (raw / "unsafe-link").symlink_to(fresh_raw)

            store = ReviewStore(data_path)
            with patch("nexus.review.store._now", return_value="2026-08-01T09:00:00Z"):
                rejected = store.enqueue(
                    create_review_item(
                        candidate_kind="memory",
                        candidate={"statement": "synthetic rejected candidate"},
                        reason_codes=("medium_confidence",),
                        source_refs=(_source_ref(),),
                    )
                )
                store.decide(rejected.id, action="reject")

            before = {
                path.relative_to(data_path).as_posix(): path.read_bytes()
                for path in data_path.rglob("*")
                if path.is_file() and not path.is_symlink()
            }
            report = plan_retention(self._config(data_path), now=now)
            after = {
                path.relative_to(data_path).as_posix(): path.read_bytes()
                for path in data_path.rglob("*")
                if path.is_file() and not path.is_symlink()
            }

            self.assertEqual(before, after)
            self.assertEqual(2, report.raw.total_files)
            self.assertEqual(1, report.raw.expired_files)
            self.assertEqual(1, report.raw.unsafe_entries)
            self.assertEqual(1, report.quarantine.expired_files)
            self.assertEqual(1, report.rejected_candidates.expired_items)
            self.assertGreater(report.rejected_candidates.expired_candidate_bytes, 0)
            self.assertFalse(report.to_dict()["writes_performed"])

    def test_missing_data_path_stays_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "missing"

            report = plan_retention(
                self._config(data_path), now=datetime(2026, 9, 17, tzinfo=UTC)
            )

            self.assertFalse(data_path.exists())
            self.assertEqual(0, report.raw.total_files)
            self.assertEqual(0, report.rejected_candidates.total_items)

    def test_symlink_data_path_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)

            with self.assertRaises(RetentionError):
                plan_retention(
                    self._config(link), now=datetime(2026, 9, 17, tzinfo=UTC)
                )


if __name__ == "__main__":
    unittest.main()
