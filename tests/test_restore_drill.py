from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.errors import RestoreDrillError
from nexus.restore_drill import run_synthetic_restore_drill


class RestoreDrillTests(unittest.TestCase):
    def test_synthetic_restore_has_hash_index_and_cleanup_parity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            report = run_synthetic_restore_drill(temp_parent=parent)

            self.assertTrue(report.to_dict()["ok"])
            self.assertEqual(4, report.records)
            self.assertEqual(1, report.open_commitments)
            self.assertTrue(report.canonical_hashes_match)
            self.assertTrue(report.index_parity)
            self.assertTrue(report.private_permissions)
            self.assertTrue(report.cleanup_verified)
            self.assertEqual([], list(parent.iterdir()))
            self.assertFalse(report.to_dict()["production_paths_accessed"])
            self.assertFalse(report.to_dict()["production_writes"])

    def test_restore_corruption_fails_closed(self) -> None:
        from nexus import restore_drill

        original_copy = restore_drill._copy_tree
        calls = 0

        def corrupt_restored_copy(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            original_copy(source, destination)
            if calls == 2:
                target = next(path for path in destination.rglob("*") if path.is_file())
                target.write_bytes(target.read_bytes() + b"corrupt")

        with tempfile.TemporaryDirectory() as directory, patch(
            "nexus.restore_drill._copy_tree", side_effect=corrupt_restored_copy
        ):
            parent = Path(directory)
            with self.assertRaisesRegex(RestoreDrillError, "hash parity"):
                run_synthetic_restore_drill(temp_parent=parent)
            self.assertEqual([], list(parent.iterdir()))

    def test_symlinked_temporary_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            link = Path(directory) / "unsafe-parent"
            link.symlink_to(Path(outside), target_is_directory=True)

            with self.assertRaisesRegex(RestoreDrillError, "temporary parent"):
                run_synthetic_restore_drill(temp_parent=link)
            self.assertEqual([], list(Path(outside).iterdir()))


if __name__ == "__main__":
    unittest.main()
