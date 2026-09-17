from __future__ import annotations

import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import nexus_ingest_cron, nexus_reminder_cron


class CronWrapperTests(unittest.TestCase):
    def test_reminder_wrapper_keeps_empty_stdout_silent(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        stream = io.StringIO()
        with (
            patch("scripts.nexus_reminder_cron.shutil.which", return_value="/bin/hermes"),
            patch("scripts.nexus_reminder_cron.subprocess.run", return_value=completed) as run,
            contextlib.redirect_stdout(stream),
        ):
            result = nexus_reminder_cron.main()

        self.assertEqual(0, result)
        self.assertEqual("", stream.getvalue())
        self.assertEqual(
            ["/bin/hermes", "nexus", "reminders", "--emit-local"],
            run.call_args.args[0],
        )
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_ingest_probe_reports_counts_without_source_content(self) -> None:
        payload = {
            "ok": True,
            "summary": {"rejected": 2},
            "errors": [],
            "private_text": "must never be printed",
        }
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
        stream = io.StringIO()
        with (
            patch("scripts.nexus_ingest_cron.shutil.which", return_value="/bin/hermes"),
            patch("scripts.nexus_ingest_cron.subprocess.run", return_value=completed),
            contextlib.redirect_stdout(stream),
        ):
            result = nexus_ingest_cron.main()

        self.assertEqual(0, result)
        self.assertEqual("NEXUS ingest probe: rejected=2, errors=0\n", stream.getvalue())
        self.assertNotIn("must never be printed", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
