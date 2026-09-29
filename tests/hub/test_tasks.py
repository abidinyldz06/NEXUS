from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from nexus.config import NexusConfig
from nexus.hub.tasks import TaskDraftError, create_draft, list_drafts


def _draft() -> dict[str, object]:
    return {
        "title": "Araştırma taslağı",
        "goal": "Seçilen konunun kaynaklarını araştır",
        "expected_output": "Kaynaklı kısa özet",
        "target_app": "Hermes",
    }


class TaskDraftTests(unittest.TestCase):
    def test_listing_absent_store_does_not_create_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "private"
            config = NexusConfig.from_mapping({"data_path": str(data)})
            self.assertEqual([], list_drafts(config)["items"])
            self.assertFalse(data.exists())

    def test_draft_is_persistent_and_never_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            key = str(uuid4())
            first = create_draft(config, _draft(), idempotency_key=key)
            repeated = create_draft(config, _draft(), idempotency_key=key)
            after_restart = list_drafts(
                NexusConfig.from_mapping({"data_path": str(config.data_path)})
            )
            self.assertTrue(first["created"])
            self.assertFalse(repeated["created"])
            self.assertFalse(first["dispatched"])
            self.assertEqual(first["task"]["id"], repeated["task"]["id"])
            self.assertEqual(1, after_restart["total"])
            self.assertEqual("draft", after_restart["items"][0]["status"])
            self.assertEqual("undetermined", after_restart["items"][0]["data_class"])
            self.assertIsNone(after_restart["items"][0]["hermes_run_id"])
            self.assertEqual(
                0o600, (config.data_path / "hub" / "tasks.sqlite3").stat().st_mode & 0o777
            )

    def test_same_key_cannot_change_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            key = str(uuid4())
            create_draft(config, _draft(), idempotency_key=key)
            changed = {**_draft(), "target_app": "GitHub"}
            with self.assertRaisesRegex(TaskDraftError, "aynı işlem kimliği"):
                create_draft(config, changed, idempotency_key=key)
            self.assertEqual(1, list_drafts(config)["total"])

    def test_session_reference_survives_restart_without_claiming_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            fields = {**_draft(), "hermes_session_id": "session_12345678"}
            created = create_draft(config, fields, idempotency_key=str(uuid4()))
            reopened = list_drafts(config)["items"][0]
            self.assertEqual("session_12345678", created["task"]["hermes_session_id"])
            self.assertEqual("session_12345678", reopened["hermes_session_id"])
            self.assertFalse(reopened["hermes_reference_verified"])
            self.assertEqual("draft", reopened["status"])
            self.assertIsNone(reopened["hermes_run_id"])

    def test_session_reference_is_restricted_to_hermes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            fields = {**_draft(), "target_app": "GitHub", "hermes_session_id": "session_12345678"}
            with self.assertRaisesRegex(TaskDraftError, "oturum kimliği"):
                create_draft(config, fields, idempotency_key=str(uuid4()))
            fields = {**_draft(), "hermes_session_id": "../unsafe"}
            with self.assertRaisesRegex(TaskDraftError, "oturum kimliği"):
                create_draft(config, fields, idempotency_key=str(uuid4()))
            self.assertFalse(config.data_path.exists())

    def test_data_scope_is_explicit_and_unapproved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            fields = {**_draft(), "data_class": "selected_external"}
            saved = create_draft(config, fields, idempotency_key=str(uuid4()))["task"]
            self.assertEqual("selected_external", saved["data_class"])
            self.assertEqual("onaylanmadı", saved["permission_scope"])
            self.assertIsNone(saved["hermes_run_id"])
            with self.assertRaisesRegex(TaskDraftError, "veri kapsamı"):
                create_draft(
                    config, {**_draft(), "data_class": "send_everything"},
                    idempotency_key=str(uuid4()),
                )

    def test_old_draft_optional_fields_do_not_break_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            key = str(uuid4())
            first = create_draft(config, _draft(), idempotency_key=key)
            path = config.data_path / "hub" / "tasks.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE drafts SET payload_json = ? WHERE id = ?",
                    (json.dumps(_draft()), first["task"]["id"]),
                )
            repeated = create_draft(config, _draft(), idempotency_key=key)
            self.assertFalse(repeated["created"])
            self.assertEqual(first["task"]["id"], repeated["task"]["id"])
            self.assertEqual("undetermined", list_drafts(config)["items"][0]["data_class"])

    def test_concurrent_same_key_creates_one_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"data_path": str(Path(directory) / "private")})
            key = str(uuid4())
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(
                    pool.map(
                        lambda _: create_draft(config, _draft(), idempotency_key=key),
                        range(2),
                    )
                )
            self.assertEqual(1, sum(bool(item["created"]) for item in outcomes))
            self.assertEqual(1, list_drafts(config)["total"])

    def test_invalid_input_and_symlink_store_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = NexusConfig.from_mapping({"data_path": str(root / "private")})
            with self.assertRaises(TaskDraftError):
                create_draft(config, {**_draft(), "title": " "}, idempotency_key=str(uuid4()))
            with self.assertRaises(TaskDraftError):
                create_draft(config, _draft(), idempotency_key="not-a-uuid")
            (root / "private").symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(TaskDraftError, "güvenli değil"):
                create_draft(config, _draft(), idempotency_key=str(uuid4()))


if __name__ == "__main__":
    unittest.main()
