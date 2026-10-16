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
    FAILED_SEGMENT,
    LONG_UNIT_DEFAULT_SECONDS,
    V2_HARD_TIMEOUT_SECONDS,
    V2_TARGET_TIMEOUT_SECONDS,
    _percentile,
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

    def test_p95_gate_uses_first_attempt_and_adr_target(self) -> None:
        source = inspect.getsource(acceptance_report)
        self.assertNotIn("p95_lt_60", source)
        self.assertNotIn("p95_all < 60", source)
        self.assertIn("p95_first <= V2_TARGET_TIMEOUT_SECONDS", source)

        historical = (
            {
                "segment_status": "completed",
                "attempt_count": 3,
                "timeout_count": 0,
                "segment_duration_ms": 342_000,
            },
            {
                "segment_status": FAILED_SEGMENT,
                "attempt_count": 3,
                "timeout_count": 3,
                "segment_duration_ms": 145_000,
            },
        )
        first_attempts = (
            {
                "segment_status": "completed",
                "attempt_count": 1,
                "timeout_count": 0,
                "segment_duration_ms": 82_053,
            },
        ) * 20
        under = self._report(first_attempts + historical)
        measured = [82.053] * 20 + [342.0, 145.0]
        self.assertEqual(120, under["thresholds"]["p95_target_seconds"])
        self.assertEqual(V2_TARGET_TIMEOUT_SECONDS, under["thresholds"]["p95_target_seconds"])
        self.assertEqual(
            "p95_first_attempt_completed_seconds",
            under["thresholds"]["p95_threshold_metric"],
        )
        self.assertEqual("0004", under["thresholds"]["p95_threshold_adr"])
        self.assertNotIn("p95_lt_60", under["thresholds"])
        self.assertEqual(82.053, under["p95_first_attempt_completed_seconds"])
        self.assertEqual(round(_percentile(measured, 95), 3), under["p95_segment_seconds"])
        self.assertGreater(under["p95_segment_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertTrue(under["thresholds"]["p95_le_target"])
        self.assertEqual(len(measured), under["segment_duration_samples"])

        exact = self._report(
            (
                {
                    "segment_status": "completed",
                    "attempt_count": 1,
                    "timeout_count": 0,
                    "segment_duration_ms": int(V2_TARGET_TIMEOUT_SECONDS * 1000),
                },
            )
            + historical
        )
        self.assertEqual(float(V2_TARGET_TIMEOUT_SECONDS), exact["p95_first_attempt_completed_seconds"])
        self.assertGreater(exact["p95_segment_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertTrue(exact["thresholds"]["p95_le_target"])

        short_retries = (
            {
                "segment_status": "completed",
                "attempt_count": 2,
                "timeout_count": 1,
                "segment_duration_ms": 10_000,
            },
        ) * 40
        over = self._report(
            short_retries
            + (
                {
                    "segment_status": "completed",
                    "attempt_count": 1,
                    "timeout_count": 0,
                    "segment_duration_ms": int(V2_TARGET_TIMEOUT_SECONDS * 1000) + 1,
                },
            )
        )
        self.assertLess(over["p95_segment_seconds"], V2_TARGET_TIMEOUT_SECONDS)
        self.assertGreater(
            over["p95_first_attempt_completed_seconds"], V2_TARGET_TIMEOUT_SECONDS
        )
        self.assertFalse(over["thresholds"]["p95_le_target"])

        empty = self._report(())
        self.assertIsNone(empty["p95_first_attempt_completed_seconds"])
        self.assertIsNone(empty["p95_segment_seconds"])
        self.assertFalse(empty["thresholds"]["p95_le_target"])

    def _report(self, rows: tuple[dict[str, object], ...]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            if rows:
                path = ingest_log_path(data)
                path.parent.mkdir(parents=True)
                path.write_text(
                    "".join(json.dumps(row) + "\n" for row in rows),
                    encoding="utf-8",
                )
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
