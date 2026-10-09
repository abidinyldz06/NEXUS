"""Persistent safe failure evidence. Disposable ledgers and a fake provider only."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from nexus.hub import operation_status, pilot
from nexus.hub.budget import BudgetError, PilotBudget


SECRET = "sk-or-synthetic-secret"
PROMPT = "gizli-istem-metni"


class DiagnosticEvidenceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.config = SimpleNamespace(data_path=self.root, auto_publish_enabled=False)
        self.model = "poolside/laguna-s-2.1:free"
        catalog = {"data": [{"id": self.model, "pricing": {"prompt": "0", "completion": "0"}}]}
        self.enterContext(patch.object(pilot.free_model, "read_catalog", return_value=catalog))
        self.enterContext(patch.object(
            pilot.providers, "_credentials", return_value={"api_key": "sk-or-synthetic"}))
        self.transport = self.enterContext(patch.object(pilot.free_model, "_transport"))

    def path(self) -> Path:
        return self.root / "hub" / "free-pilot.sqlite3"

    def run_pilot(self, identifier=None, payload=(200, {
        "model": "poolside/laguna-s-2.1:free", "usage": {"cost": 0},
        "choices": [{"message": {"content": "NEXUS_FREE_OK"}}],
    })):
        self.transport.side_effect = None
        self.transport.return_value = payload
        return pilot.run(self.config, request_id=identifier or str(uuid4()), model=self.model)

    def diagnostic(self, identifier):
        with closing(sqlite3.connect(self.path())) as connection:
            return connection.execute(
                "SELECT model, phase, http_status, error_class, finished_at IS NOT NULL "
                "FROM diagnostics WHERE id=?", (identifier,)
            ).fetchone()

    def hold(self, identifier):
        with closing(sqlite3.connect(self.path())) as connection:
            return connection.execute(
                "SELECT status, actual FROM holds WHERE id=?", (identifier,)
            ).fetchone()

    def assert_no_secret(self):
        raw = self.path().read_bytes()
        self.assertNotIn(SECRET.encode(), raw)
        self.assertNotIn(PROMPT.encode(), raw)
        self.assertNotIn(b"private-error", raw)

    def test_http_rejection_is_not_a_zero_cost_and_hides_the_body(self):
        for status in (404, 429):
            with self.subTest(status=status):
                root = Path(self.temp.name) / str(status)
                root.mkdir(mode=0o700)
                config = SimpleNamespace(data_path=root, auto_publish_enabled=False)
                identifier = str(uuid4())
                with patch.object(pilot.free_model, "_transport",
                                  return_value=(status, {"error": SECRET, "prompt": PROMPT})) as transport:
                    result = pilot.run(config, request_id=identifier, model=self.model)
                self.assertEqual("http_rejected", result["error_class"])
                self.assertEqual(status, result["http_status"])
                self.assertFalse(result["cost_verified"])
                self.assertIsNone(result["cost_usd"])
                self.assertNotIn("output", result)
                self.assertNotIn(SECRET, str(result))
                self.assertNotIn(PROMPT, str(result))
                transport.assert_called_once()
                path = root / "hub" / "free-pilot.sqlite3"
                raw = path.read_bytes()
                self.assertNotIn(SECRET.encode(), raw)
                self.assertNotIn(PROMPT.encode(), raw)
                with closing(sqlite3.connect(path)) as connection:
                    row = connection.execute(
                        "SELECT d.http_status, d.error_class, h.actual FROM diagnostics d "
                        "JOIN holds h ON h.id=d.id"
                    ).fetchone()
                self.assertEqual((status, "http_rejected", None), row)
                first = operation_status.snapshot(config)["items"][0]
                second = operation_status.snapshot(config)["items"][0]
                self.assertEqual(first, second)
                self.assertEqual(status, second["http_status"])
                self.assertEqual("http_rejected", second["error_class"])

    def test_timeout_invalid_response_and_verified_zero_are_separate_records(self):
        timed = str(uuid4())
        self.transport.side_effect = TimeoutError("private-error")
        result = pilot.run(self.config, request_id=timed, model=self.model)
        self.assertEqual("timeout", result["error_class"])
        self.assertIsNone(result["http_status"])
        self.assertFalse(result["cost_verified"])
        self.assertNotIn("private-error", str(result))
        self.assertEqual((self.model, "unknown", None, "timeout", 1), self.diagnostic(timed))
        self.assertEqual(("unknown", None), self.hold(timed))
        self.assert_no_secret()

    def test_invalid_response_is_not_a_zero_cost(self):
        folder = self.root / "other"
        folder.mkdir(mode=0o700)
        config = SimpleNamespace(data_path=folder, auto_publish_enabled=False)
        identifier = str(uuid4())
        with patch.object(pilot.free_model, "_transport", return_value=(200, {"error": SECRET, "prompt": PROMPT})):
            result = pilot.run(config, request_id=identifier, model=self.model)
        self.assertEqual("unverified_cost", result["error_class"])
        self.assertEqual(200, result["http_status"])
        self.assertIsNone(result["cost_usd"])
        self.assertNotIn("output", result)
        path = folder / "hub" / "free-pilot.sqlite3"
        raw = path.read_bytes()
        self.assertNotIn(SECRET.encode(), raw)
        self.assertNotIn(PROMPT.encode(), raw)
        with closing(sqlite3.connect(path)) as connection:
            row = connection.execute(
                "SELECT http_status, error_class, actual FROM diagnostics "
                "JOIN holds ON holds.id=diagnostics.id"
            ).fetchone()
        self.assertEqual((200, "unverified_cost", None), row)
        invalid_root = Path(self.temp.name) / "invalid"
        invalid_root.mkdir(mode=0o700)
        invalid_config = SimpleNamespace(data_path=invalid_root, auto_publish_enabled=False)
        with patch.object(pilot.free_model, "_transport", return_value=(200, SECRET)):
            invalid = pilot.run(invalid_config, request_id=str(uuid4()), model=self.model)
        self.assertEqual("invalid_response", invalid["error_class"])
        self.assertEqual(200, invalid["http_status"])
        self.assertIsNone(invalid["cost_usd"])
        self.assertNotIn(SECRET, str(invalid))
        invalid_path = invalid_root / "hub" / "free-pilot.sqlite3"
        self.assertNotIn(SECRET.encode(), invalid_path.read_bytes())

    def test_verified_zero_keeps_http_and_does_not_look_like_a_rejection(self):
        identifier = str(uuid4())
        result = self.run_pilot(identifier)
        self.assertEqual("verified_zero", result["error_class"])
        self.assertEqual(200, result["http_status"])
        self.assertEqual(0, result["cost_usd"])
        self.assertEqual("draft_result", operation_status.snapshot(self.config)["items"][0]["state"])
        self.assertEqual((self.model, "draft_result", 200, "verified_zero", 1), self.diagnostic(identifier))
        self.assertEqual(("settled", 0), self.hold(identifier))
        self.assert_no_secret()

    def test_reopen_preserves_metadata_budget_and_generation_link(self):
        identifier = str(uuid4())
        self.run_pilot(identifier, (200, {
            "id": "gen-aaaaaaaa", "model": self.model, "usage": {"cost": 0},
            "choices": [{"message": {"content": "NEXUS_FREE_OK"}}], "prompt": PROMPT,
        }))
        with closing(sqlite3.connect(self.path())) as connection:
            before = connection.execute(
                "SELECT h.status, h.actual, d.model, d.http_status, d.error_class, d.started_at, "
                "d.finished_at, g.generation_id FROM holds h "
                "JOIN diagnostics d ON d.id=h.id LEFT JOIN generation_refs g ON g.id=h.id"
            ).fetchone()
        reopened = operation_status.snapshot(self.config)
        item = reopened["items"][0]
        self.assertEqual(200, item["http_status"])
        self.assertEqual("verified_zero", item["error_class"])
        self.assertEqual(self.model, item["requested_model"])
        self.assertTrue(item["started_at"])
        self.assertTrue(item["finished_at"])
        self.assertEqual("gen-aaaaaaaa", item["generation_id"])
        self.assertTrue(item["cost_verified"])
        self.assertEqual("settled", item["hold_status"])
        with closing(sqlite3.connect(self.path())) as connection:
            after = connection.execute(
                "SELECT h.status, h.actual, d.model, d.http_status, d.error_class, d.started_at, "
                "d.finished_at, g.generation_id FROM holds h "
                "JOIN diagnostics d ON d.id=h.id LEFT JOIN generation_refs g ON g.id=h.id"
            ).fetchone()
        self.assertEqual(before, after)
        self.assert_no_secret()

    def test_legacy_ledger_without_diagnostics_reads_without_writing(self):
        folder = self.root / "hub"
        folder.mkdir(mode=0o700)
        ledger = PilotBudget(folder / "free-pilot.sqlite3", per_job_usd="0",
                             daily_usd="0", monthly_usd="0")
        identifier = str(uuid4())
        ledger.reserve(identifier, ceiling_usd="0")
        ledger.reconcile(identifier, verified_cost_usd="0")
        before = hashlib.sha256(ledger.path.read_bytes()).digest()
        item = operation_status.snapshot(self.config)["items"][0]
        self.assertIsNone(item["http_status"])
        self.assertIsNone(item["error_class"])
        self.assertIsNone(item["requested_model"])
        self.assertEqual(before, hashlib.sha256(ledger.path.read_bytes()).digest())
        with closing(sqlite3.connect(ledger.path)) as connection:
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='diagnostics'"
            ).fetchone())

    def test_same_id_does_not_retry_or_replace_the_first_evidence(self):
        identifier = str(uuid4())
        self.run_pilot(identifier, (404, {"error": SECRET}))
        with closing(sqlite3.connect(self.path())) as connection:
            before = connection.execute("SELECT * FROM diagnostics").fetchone()
        again = self.run_pilot(identifier, (200, {"usage": {"cost": 0}, "model": self.model,
                                       "choices": [{"message": {"content": "NEXUS_FREE_OK"}}]}))
        self.assertEqual("already_recorded", again["status"])
        self.assertFalse(again["inference_attempted"])
        self.transport.assert_called_once()
        with closing(sqlite3.connect(self.path())) as connection:
            after = connection.execute("SELECT * FROM diagnostics").fetchone()
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM diagnostics").fetchone()[0])
        self.assertEqual(before, after)
        self.assertEqual(("unknown", None), self.hold(identifier))
        with self.assertRaises(BudgetError):
            pilot.run(self.config, request_id=str(uuid4()), model=self.model)
        self.transport.assert_called_once()
        reopened = PilotBudget(self.path(), per_job_usd="0", daily_usd="0", monthly_usd="0")
        with self.assertRaises(BudgetError):
            reopened.reserve(str(uuid4()), ceiling_usd="0")

    def test_diagnostic_write_failure_does_not_settle_zero(self):
        identifier = str(uuid4())
        with patch.object(PilotBudget, "finish_diagnostic", side_effect=BudgetError("yazılamadı")):
            with self.assertRaises(BudgetError) as caught:
                self.run_pilot(identifier)
        self.assertNotIn("yazılamadı", str(caught.exception))
        self.assertEqual(("unknown", None), self.hold(identifier))
        self.transport.assert_called_once()
        snapshot = operation_status.snapshot(self.config)
        self.assertFalse(snapshot["items"][0]["cost_verified"])
        self.assertNotEqual("verified_zero", snapshot["items"][0]["error_class"])
