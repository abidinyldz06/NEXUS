from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from nexus.hub.budget import BudgetError, PilotBudget, validate_pilot_scope


class PilotBudgetTests(unittest.TestCase):
    def setUp(self):
        # Resolve macOS /var or /tmp aliases, keeping tests in disposable storage.
        self.directory = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "budget.sqlite3"
        self.budget = self.open_budget()
        self.now = datetime(2026, 9, 30, 10, tzinfo=UTC)

    def open_budget(self, **kwargs):
        return PilotBudget(self.path, **({"per_job_usd": "0.1", "daily_usd": "0.2",
                                         "monthly_usd": "0.3"} | kwargs))

    def reserve(self, identifier=None, ceiling="0.1", now=None):
        identifier = identifier or str(uuid4())
        return identifier, self.budget.reserve(identifier, ceiling_usd=ceiling, now=now or self.now)

    def test_constructor_does_not_create_a_ledger(self):
        self.assertFalse(self.path.exists())

    def test_free_only_zero_caps_keep_single_flight_and_unknown_protection(self):
        free = self.open_budget(per_job_usd="0", daily_usd="0", monthly_usd="0")
        identifier = str(uuid4())
        self.assertTrue(free.reserve(identifier, ceiling_usd="0")["created"])
        free.reconcile(identifier, verified_cost_usd=None)
        with self.assertRaises(BudgetError):
            free.reserve(str(uuid4()), ceiling_usd="0")
        with self.assertRaises(BudgetError):
            free.reserve(str(uuid4()), ceiling_usd="0.000001")
        free.reconcile(identifier, verified_cost_usd="0")
        self.assertTrue(free.reserve(str(uuid4()), ceiling_usd="0")["created"])

    def test_invalid_budget_and_id_rejected_before_file_creation(self):
        for amount in (None, True, 1, "NaN", "Infinity", "-1", "0.0000001", "1001", "bad",
                       "0.100000000000000000000000000001"):
            with self.subTest(amount=amount), self.assertRaises(BudgetError):
                self.budget.reserve(str(uuid4()), ceiling_usd=amount)
        with self.assertRaises(BudgetError):
            self.budget.reserve("invalid", ceiling_usd="0.1")
        self.assertFalse(self.path.exists())

    def test_caps_are_positive_ordered_and_immutable(self):
        for args in ({"per_job_usd": "0"}, {"daily_usd": "0.01"}, {"monthly_usd": "0.1"}):
            with self.assertRaises(BudgetError):
                self.open_budget(**args)
        self.reserve()
        with self.assertRaises(BudgetError):
            self.open_budget(monthly_usd="1").reserve(str(uuid4()), ceiling_usd="0.1")

    def test_idempotent_hold_is_not_a_second_execution_permission(self):
        identifier, result = self.reserve()
        self.assertTrue(result["created"])
        self.assertFalse(result["dispatch_enabled"])
        _, repeat = self.reserve(identifier)
        self.assertFalse(repeat["created"])
        with self.assertRaises(BudgetError):
            self.reserve(identifier, ceiling="0.05")

    def test_one_flight_and_unknown_timeout_survive_restart_and_month_rollover(self):
        identifier, _ = self.reserve()
        self.assertEqual("unknown", self.budget.reconcile(
            identifier, verified_cost_usd=None)["status"])
        reopened = self.open_budget()
        with self.assertRaises(BudgetError):
            reopened.reserve(str(uuid4()), ceiling_usd="0.1",
                             now=datetime(2026, 10, 1, tzinfo=UTC))
        reopened.reconcile(identifier, verified_cost_usd="0.04")
        self.assertTrue(reopened.reserve(str(uuid4()), ceiling_usd="0.1",
                                        now=self.now)["created"])

    def test_exact_daily_cap_and_monthly_cap_block_additional_holds(self):
        yesterday = datetime(2026, 9, 29, 10, tzinfo=UTC)
        for _ in range(2):
            identifier, _ = self.reserve(now=yesterday)
            self.budget.reconcile(identifier, verified_cost_usd="0.1")
        with self.assertRaises(BudgetError):
            self.reserve(ceiling="0.000001", now=yesterday)
        # Earlier days in the same month contribute to monthly, not daily cap.
        identifier, _ = self.reserve()
        self.budget.reconcile(identifier, verified_cost_usd="0.1")
        with self.assertRaises(BudgetError):
            self.reserve(ceiling="0.000001")

    def test_empty_unknown_stays_blocking_after_accept_restart_and_same_id(self):
        identifier, _ = self.reserve()
        self.budget.reconcile(identifier, verified_cost_usd=None)
        released = self.budget.accept_unknown(identifier)
        self.assertEqual("accepted", released["status"])
        self.assertFalse(released["cost_verified"])
        self.assertFalse(released["dispatch_enabled"])
        with closing(self.budget._connect()) as connection:
            row = connection.execute(
                "SELECT status, actual FROM holds WHERE id=?", (identifier,)
            ).fetchone()
            connection.rollback()
        self.assertEqual(("accepted", None), row)
        with self.assertRaises(BudgetError):
            self.budget.reserve(str(uuid4()), ceiling_usd="0.1")
        reopened = self.open_budget()
        with self.assertRaises(BudgetError):
            reopened.reserve(str(uuid4()), ceiling_usd="0.1")
        again = reopened.reserve(identifier, ceiling_usd="0.1")
        self.assertFalse(again["created"])
        self.assertEqual("accepted", again["status"])
        self.assertFalse(again["dispatch_enabled"])
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM holds").fetchone()[0])
            self.assertIsNone(connection.execute("SELECT actual FROM holds").fetchone()[0])
        with self.assertRaises(BudgetError):
            reopened.reconcile(identifier, verified_cost_usd="0")

    def test_unknown_never_clears_verified_cost_and_zero_can_be_verified(self):
        identifier, _ = self.reserve()
        self.budget.reconcile(identifier, verified_cost_usd="0")
        self.budget.reconcile(identifier, verified_cost_usd="0.000000")
        with self.assertRaises(BudgetError):
            self.budget.reconcile(identifier, verified_cost_usd=None)
        with self.assertRaises(BudgetError):
            self.budget.reconcile(identifier, verified_cost_usd="0.01")
        self.reserve()

    def test_overrun_is_recorded_and_blocks_further_work(self):
        identifier, _ = self.reserve()
        result = self.budget.reconcile(identifier, verified_cost_usd="0.12")
        self.assertEqual("overrun", result["status"])
        with self.assertRaises(BudgetError):
            self.reserve()
        with sqlite3.connect(self.path) as connection:
            self.assertEqual(120000, connection.execute("SELECT actual FROM holds").fetchone()[0])

    def test_two_connections_cannot_reserve_the_same_capacity(self):
        def reserve_one(_):
            try:
                return self.open_budget().reserve(str(uuid4()), ceiling_usd="0.1")["created"]
            except BudgetError:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual([False, True], sorted(executor.map(reserve_one, range(2))))

    def test_symlink_and_public_file_are_rejected(self):
        target = Path(self.directory.name) / "untouched"
        target.write_text("synthetic", encoding="utf8")
        self.path.symlink_to(target)
        with self.assertRaises(BudgetError):
            self.reserve()
        self.assertEqual("synthetic", target.read_text(encoding="utf8"))
        self.path.unlink()  # Only this disposable test symlink.
        self.path.touch(mode=0o644)
        os.chmod(self.path, 0o644)
        with self.assertRaises(BudgetError):
            self.reserve()

    def test_scope_rejects_sensitive_unknown_local_content_and_application_provider(self):
        for data in ("sensitive", "local_only", "undetermined"):
            with self.assertRaises(BudgetError):
                validate_pilot_scope(provider="openrouter", model="synthetic-model",
                                     data_class=data, external_authorized=True)
        for auth in (False, None, 1, "yes"):
            with self.assertRaises(BudgetError):
                validate_pilot_scope(provider="nvidia", model="synthetic-model",
                                     data_class="synthetic", external_authorized=auth)
        with self.assertRaises(BudgetError):
            validate_pilot_scope(provider="antigravity", model="synthetic-model",
                                 data_class="selected_external", external_authorized=True)
        for provider in ("openrouter", "nvidia", "gemini"):
            validate_pilot_scope(provider=provider, model="synthetic-model",
                                 data_class="synthetic", external_authorized=True)

    def test_missing_model_and_naive_timestamp_rejected(self):
        with self.assertRaises(BudgetError):
            validate_pilot_scope(provider="openrouter", model="", data_class="synthetic",
                                 external_authorized=True)
        with self.assertRaises(BudgetError):
            self.budget.reserve(str(uuid4()), ceiling_usd="0.1", now=datetime(2026, 9, 30))
        self.assertFalse(self.path.exists())

    def test_reconciliation_of_missing_hold_does_not_create_store(self):
        with self.assertRaises(BudgetError):
            self.budget.reconcile(str(uuid4()), verified_cost_usd="0")
        self.assertFalse(self.path.exists())
