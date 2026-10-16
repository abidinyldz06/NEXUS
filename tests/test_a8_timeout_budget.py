"""A8 timeout budget: ADR 0004 accepted 16.10.2026 — 120s target / 150s hard cap. Guard stays: values must not drift from the accepted ADR."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nexus.config import NexusConfig
from nexus.ingest_v2 import (
    LONG_UNIT_DEFAULT_SECONDS,
    V2_HARD_TIMEOUT_SECONDS,
    V2_TARGET_TIMEOUT_SECONDS,
    acceptance_report,
    ingest_log_path,
)

ROOT = Path(__file__).resolve().parents[1]


class TimeoutBudgetTests(unittest.TestCase):
    def test_defaults_are_not_silently_raised(self) -> None:
        self.assertEqual(V2_TARGET_TIMEOUT_SECONDS, 120)
        self.assertEqual(V2_HARD_TIMEOUT_SECONDS, 150)
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

    def test_long_unit_samples_do_not_move_the_routine_target(self) -> None:
        source = inspect.getsource(acceptance_report)
        self.assertNotIn("p95_lt_60", source)
        self.assertNotIn("p95_all < 60", source)
        rows = []
        for index in range(10):
            rows.append(self._completed(f"routine-{index}", 10_000, conversation="routine"))
        for index in range(40):
            segment = f"lane-{index}"
            rows.append(
                {
                    "conversation_id": "lane-conv",
                    "segment_id": None,
                    "segment_status": None,
                    "attempt_count": None,
                    "segment_duration_ms": None,
                    "long_unit": {
                        "segment_id": segment,
                        "timeout_seconds": LONG_UNIT_DEFAULT_SECONDS,
                        "human_triggered": True,
                    },
                }
            )
            rows.append(self._completed(segment, 180_000, conversation="lane-conv"))
        payload = self._report(rows)
        self.assertEqual(50, payload["first_attempt_window"])
        self.assertEqual(10, payload["routine_first_attempt_samples"])
        self.assertEqual(40, payload["long_unit_first_attempt_samples"])
        self.assertLess(payload["p95_routine_first_attempt_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertGreater(payload["p95_long_unit_first_attempt_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertLessEqual(
            payload["p95_long_unit_first_attempt_seconds"], LONG_UNIT_DEFAULT_SECONDS
        )
        self.assertTrue(payload["thresholds"]["p95_le_target"])
        self.assertTrue(payload["thresholds"]["p95_le_long_unit_budget"])
        self.assertEqual(V2_TARGET_TIMEOUT_SECONDS, payload["thresholds"]["p95_target_seconds"])
        self.assertEqual(LONG_UNIT_DEFAULT_SECONDS, payload["thresholds"]["long_unit_budget_seconds"])
        self.assertEqual("0004", payload["thresholds"]["p95_threshold_adr"])
        self.assertNotIn("p95_lt_60", payload["thresholds"])
        self.assertGreater(payload["p95_first_attempt_completed_seconds"], V2_TARGET_TIMEOUT_SECONDS)

        over_budget = self._report(
            [self._completed(f"routine-over-{index}", 10_000) for index in range(10)]
            + [
                {
                    "conversation_id": "lane-conv",
                    "long_unit": {"segment_id": f"lane-over-{index}", "timeout_seconds": 300},
                }
                for index in range(3)
            ]
            + [
                self._completed(f"lane-over-{index}", 301_000, conversation="lane-conv")
                for index in range(3)
            ]
        )
        self.assertTrue(over_budget["thresholds"]["p95_le_target"])
        self.assertGreater(
            over_budget["p95_long_unit_first_attempt_seconds"], LONG_UNIT_DEFAULT_SECONDS
        )
        self.assertFalse(over_budget["thresholds"]["p95_le_long_unit_budget"])

    def test_first_attempt_window_drops_aged_routine_samples(self) -> None:
        slow = [self._completed(f"old-{index}", 400_000) for index in range(3)]
        fast = [self._completed(f"new-{index}", 10_000) for index in range(47)]
        inside = self._report(slow + fast)
        self.assertGreater(inside["p95_routine_first_attempt_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertFalse(inside["thresholds"]["p95_le_target"])

        aged = self._report(slow + fast + [self._completed(f"newer-{index}", 10_000) for index in range(3)])
        self.assertEqual(50, aged["routine_first_attempt_samples"])
        self.assertLess(aged["p95_routine_first_attempt_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertTrue(aged["thresholds"]["p95_le_target"])
        self.assertGreater(aged["p95_first_attempt_completed_seconds"], V2_TARGET_TIMEOUT_SECONDS)

    def _completed(self, segment_id: str, duration_ms: int, *, conversation: str = "conv") -> dict[str, object]:
        return {
            "conversation_id": conversation,
            "segment_id": segment_id,
            "segment_status": "completed",
            "attempt_count": 1,
            "timeout_count": 0,
            "segment_duration_ms": duration_ms,
            "long_unit": None,
        }

    def _report(self, rows: list[dict[str, object]]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            path = ingest_log_path(data)
            path.parent.mkdir(parents=True)
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            config = NexusConfig.from_mapping(
                {
                    "vault_path": str(root / "vault"),
                    "inbox_path": str(root / "inbox"),
                    "data_path": str(data),
                    "ingest_pipeline_v2": True,
                    "auto_publish_enabled": False,
                }
            )
            return acceptance_report(config)


if __name__ == "__main__":
    unittest.main()
