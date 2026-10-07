import hashlib
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from types import SimpleNamespace
from unittest import TestCase
from uuid import uuid4

from nexus.hub import operation_status, pilot
from nexus.hub.budget import BudgetError, PilotBudget


class OperationStatusTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(dir=Path(gettempdir()).resolve())
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = SimpleNamespace(data_path=self.root)

    def ledger(self):
        folder = self.root / "hub"
        folder.mkdir(mode=0o700)
        return PilotBudget(folder / "free-pilot.sqlite3", per_job_usd="0", daily_usd="0", monthly_usd="0")

    def test_absent_store_read_creates_nothing(self):
        self.assertEqual([], operation_status.snapshot(self.config)["items"])
        self.assertEqual([], list(self.root.iterdir()))

    def test_legacy_settled_cost_is_not_success_and_read_does_not_migrate(self):
        ledger = self.ledger()
        identifier = str(uuid4())
        ledger.reserve(identifier, ceiling_usd="0")
        ledger.reconcile(identifier, verified_cost_usd="0")
        before = hashlib.sha256(ledger.path.read_bytes()).digest()
        result = operation_status.snapshot(self.config)
        self.assertEqual("unknown", result["items"][0]["state"])
        self.assertTrue(result["items"][0]["cost_verified"])
        self.assertFalse(result["blocked"])
        self.assertEqual(before, hashlib.sha256(ledger.path.read_bytes()).digest())
        with sqlite3.connect(ledger.path) as connection:
            self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='outcomes'").fetchone())

    def test_running_requires_live_evidence_restart_is_unknown_and_blocked(self):
        ledger = self.ledger()
        identifier = str(uuid4())
        ledger.reserve(identifier, ceiling_usd="0")
        ledger.record_outcome(identifier, "running")
        flight = (str(ledger.path), identifier)
        with pilot._active_lock:
            pilot._active.add(flight)
        try:
            self.assertEqual("running", operation_status.snapshot(self.config)["items"][0]["state"])
        finally:
            with pilot._active_lock:
                pilot._active.discard(flight)
        result = operation_status.snapshot(self.config)
        self.assertEqual("unknown", result["items"][0]["state"])
        self.assertTrue(result["blocked"])
        self.assertFalse(result["items"][0]["retry"])

    def test_accepted_empty_hold_blocks_and_read_does_not_change_it(self):
        ledger = self.ledger()
        identifier = str(uuid4())
        ledger.reserve(identifier, ceiling_usd="0")
        ledger.reconcile(identifier, verified_cost_usd=None)
        ledger.accept_unknown(identifier)
        before = hashlib.sha256(ledger.path.read_bytes()).digest()
        result = operation_status.snapshot(self.config)
        self.assertTrue(result["blocked"])
        self.assertEqual("accepted", result["items"][0]["state"])
        self.assertFalse(result["items"][0]["cost_verified"])
        self.assertFalse(result["items"][0]["retry"])
        self.assertEqual(before, hashlib.sha256(ledger.path.read_bytes()).digest())
        with self.assertRaises(BudgetError):
            ledger.reserve(str(uuid4()), ceiling_usd="0")

    def test_draft_result_requires_settled_cost(self):
        ledger = self.ledger()
        identifier = str(uuid4())
        ledger.reserve(identifier, ceiling_usd="0")
        ledger.record_outcome(identifier, "draft_result")
        self.assertEqual("unknown", operation_status.snapshot(self.config)["items"][0]["state"])
        ledger.reconcile(identifier, verified_cost_usd="0")
        item = operation_status.snapshot(self.config)["items"][0]
        self.assertEqual("draft_result", item["state"])
        self.assertFalse(item["output_saved"])
