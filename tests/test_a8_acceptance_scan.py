"""A8 acceptance scan stays read-only and takes the plugin note from git."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "a8_acceptance_scan.py"


def load_scan():
    spec = importlib.util.spec_from_file_location("a8_acceptance_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AcceptanceScanTests(unittest.TestCase):
    def test_plugin_note_follows_the_checkout_head(self) -> None:
        scan = load_scan()
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("ea2caff", source)
        self.assertNotIn("reprocess_failed", source)
        self.assertNotIn('["hermes"', source)
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.com",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.com",
            }
            subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
            (root / "README").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "README"], cwd=root, check=True, capture_output=True, env=env)
            subprocess.run(["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True, env=env)
            sha = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(f"installed {sha} shadow only", scan.plugin_note(root))
            self.assertEqual("unknown", scan.plugin_note(root / "missing"))

    def test_missing_source_is_unmatched_and_not_forced(self) -> None:
        scan = load_scan()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            checkpoints = root / "checkpoints"
            inbox.mkdir()
            checkpoints.mkdir()
            (checkpoints / "ingest_fixture.json").write_text(
                json.dumps(
                    {
                        "conversation_id": "missing-source",
                        "ingest_id": "ingest_fixture",
                        "segments": {"seg": {"status": "FAILED_SEGMENT"}},
                    }
                ),
                encoding="utf-8",
            )
            jobs, unmatched = scan.build_jobs(inbox, checkpoints)
            self.assertEqual([], jobs)
            self.assertEqual(1, unmatched)
            self.assertEqual(scan.UNMATCHED_NOTE, "unmatched = source_missing, ADR 0004 gereği zorlanmaz")


if __name__ == "__main__":
    unittest.main()
