"""A8 timeout defaults stay put until a documented budget change is accepted."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from nexus.ingest_v2 import (
    LONG_UNIT_DEFAULT_SECONDS,
    V2_HARD_TIMEOUT_SECONDS,
    V2_TARGET_TIMEOUT_SECONDS,
)

ROOT = Path(__file__).resolve().parents[1]


class TimeoutBudgetTests(unittest.TestCase):
    def test_defaults_are_not_silently_raised(self) -> None:
        self.assertEqual(V2_TARGET_TIMEOUT_SECONDS, 60)
        self.assertEqual(V2_HARD_TIMEOUT_SECONDS, 90)
        self.assertEqual(LONG_UNIT_DEFAULT_SECONDS, 300)
        self.assertLessEqual(V2_TARGET_TIMEOUT_SECONDS, V2_HARD_TIMEOUT_SECONDS)

    def test_rerun_script_refuses_to_execute(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "a8_timeout_leftover_rerun.py"), "--execute"],
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
        )
        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["rerun"], "blocked")


if __name__ == "__main__":
    unittest.main()
