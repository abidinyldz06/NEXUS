from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.errors import HermesExportError
from nexus.sources.hermes_export import build_export_command, export_sessions


class HermesExportWrapperTests(unittest.TestCase):
    def test_command_always_uses_jsonl_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sessions.jsonl"
            command = build_export_command(output, session_id="session-1")

        self.assertEqual(
            (
                "hermes",
                "sessions",
                "export",
                str(output),
                "--format",
                "jsonl",
                "--redact",
                "--session-id",
                "session-1",
            ),
            command,
        )

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sessions.jsonl"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(HermesExportError):
                build_export_command(output)

    def test_runner_uses_argument_vector_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "sessions.jsonl"

            def fake_run(command, **kwargs):
                output.write_text("{}\n", encoding="utf-8")
                self.assertNotIn("shell", kwargs)
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("nexus.sources.hermes_export.subprocess.run", side_effect=fake_run):
                result = export_sessions(output)
            self.assertEqual(output, result)
            self.assertEqual(0o600, output.stat().st_mode & 0o777)

    def test_export_parent_must_be_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            os.chmod(parent, 0o755)
            with self.assertRaisesRegex(HermesExportError, "owner-only"):
                build_export_command(parent / "sessions.jsonl")


if __name__ == "__main__":
    unittest.main()
