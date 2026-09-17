from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.errors import GitRollbackDrillError
from nexus.git_rollback_drill import run_synthetic_git_rollback_drill


class GitRollbackDrillTests(unittest.TestCase):
    def test_external_git_metadata_rolls_back_six_synthetic_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            report = run_synthetic_git_rollback_drill(temp_parent=parent)

            self.assertTrue(report.to_dict()["ok"])
            self.assertEqual(6, report.files)
            self.assertTrue(report.metadata_external)
            self.assertTrue(report.worktree_git_entry_absent)
            self.assertTrue(report.mutation_detected)
            self.assertTrue(report.rollback_hashes_match)
            self.assertTrue(report.clean_after_rollback)
            self.assertTrue(report.private_permissions)
            self.assertTrue(report.cleanup_verified)
            self.assertFalse(report.to_dict()["production_paths_accessed"])
            self.assertFalse(report.to_dict()["production_writes"])
            self.assertEqual([], list(parent.iterdir()))

    def test_missing_git_fails_without_creating_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "nexus.git_rollback_drill.shutil.which", return_value=None
        ):
            parent = Path(directory)
            with self.assertRaisesRegex(GitRollbackDrillError, "unavailable"):
                run_synthetic_git_rollback_drill(temp_parent=parent)
            self.assertEqual([], list(parent.iterdir()))

    def test_symlinked_temporary_parent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            link = Path(directory) / "unsafe-parent"
            link.symlink_to(Path(outside), target_is_directory=True)

            with self.assertRaisesRegex(GitRollbackDrillError, "temporary parent"):
                run_synthetic_git_rollback_drill(temp_parent=link)
            self.assertEqual([], list(Path(outside).iterdir()))


if __name__ == "__main__":
    unittest.main()
