from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from nexus.config import NexusConfig
from nexus.permission_audit import audit_permissions


class PermissionAuditTests(unittest.TestCase):
    def _config(self, data_path: Path, inbox_path: Path) -> NexusConfig:
        return NexusConfig.from_mapping(
            {"data_path": str(data_path), "inbox_path": str(inbox_path)}
        )

    def test_private_tree_passes_without_reading_or_writing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "private"
            raw = data_path / "raw"
            raw.mkdir(parents=True)
            secret = raw / "synthetic.json"
            secret.write_text('{"secret":"unchanged"}', encoding="utf-8")
            os.chmod(data_path, 0o700)
            os.chmod(raw, 0o700)
            os.chmod(secret, 0o600)
            before = secret.read_bytes()

            report = audit_permissions(self._config(data_path, root / "missing-inbox"))

            self.assertTrue(report.ok)
            self.assertEqual(3, report.private_data.checked_entries)
            self.assertFalse(report.inbox.present)
            self.assertEqual(before, secret.read_bytes())
            self.assertFalse(report.to_dict()["writes_performed"])

    def test_group_readable_file_and_nested_symlink_fail_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "private"
            data_path.mkdir()
            os.chmod(data_path, 0o700)
            exposed = data_path / "exposed.json"
            exposed.write_text("synthetic", encoding="utf-8")
            os.chmod(exposed, 0o640)
            (data_path / "unsafe-link").symlink_to(exposed)

            payload = audit_permissions(
                self._config(data_path, root / "missing-inbox")
            ).to_dict()

            self.assertFalse(payload["ok"])
            self.assertEqual(1, payload["private_data"]["insecure_entries"])
            self.assertEqual(1, payload["private_data"]["unsafe_entries"])
            self.assertEqual(
                {"group_or_world_access": 1, "symlink": 1},
                payload["private_data"]["issues_by_reason"],
            )

    def test_report_never_contains_entry_names_or_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "private"
            data_path.mkdir()
            os.chmod(data_path, 0o700)
            secret = data_path / "private-customer-name.json"
            secret.write_text("private-customer-content", encoding="utf-8")
            os.chmod(secret, 0o644)

            encoded = json.dumps(
                audit_permissions(self._config(data_path, root / "inbox")).to_dict()
            )

            self.assertNotIn("private-customer-name", encoded)
            self.assertNotIn("private-customer-content", encoded)


if __name__ == "__main__":
    unittest.main()
