"""Explicit OpenRouter generation-cost checks. No live key or second ledger."""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from types import SimpleNamespace
from unittest import TestCase, skipIf
from unittest.mock import Mock, patch
from uuid import uuid4

from nexus.hub import operation_status, pilot
from nexus.hub.budget import BudgetError, PilotBudget
from nexus.hub.free_model import complete_free, read_generation

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:
    FastAPI = None
    TestClient = None

GEN = "gen-aaaaaaaa"
OTHER = "gen-bbbbbbbb"
SECRET_TEXT = "gizli-metin"


def _body(cost, generation=GEN):
    return 200, {"data": {"id": generation, "total_cost": cost}, "prompt": SECRET_TEXT}


class GenerationCostTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        os.chmod(self.root, 0o700)
        self.config = SimpleNamespace(data_path=self.root, auto_publish_enabled=False)
        self.model = "stealth/space-bunny-alpha"
        self.catalog = {"data": [{"id": self.model, "pricing": {"prompt": "0", "completion": "0"}}]}
        self.secret = self.enterContext(patch.object(
            pilot.providers, "_credentials", return_value={"api_key": "sk-or-synthetic"}))
        self.chat = self.enterContext(patch.object(
            pilot.free_model, "_transport", side_effect=AssertionError("chat")))
        self.lookup = self.enterContext(patch.object(
            pilot.free_model, "read_generation", side_effect=AssertionError("lookup")))

    def ledger(self) -> PilotBudget:
        folder = self.root / "hub"
        folder.mkdir(mode=0o700, exist_ok=True)
        return PilotBudget(folder / "free-pilot.sqlite3", per_job_usd="0",
                           daily_usd="0", monthly_usd="0")

    def path(self) -> Path:
        return self.root / "hub" / "free-pilot.sqlite3"

    def seed(self, *, accepted=False, generation_id=None) -> str:
        identifier = str(uuid4())
        ledger = self.ledger()
        ledger.reserve(identifier, ceiling_usd="0")
        ledger.reconcile(identifier, verified_cost_usd=None)
        if accepted:
            ledger.accept_unknown(identifier)
        if generation_id:
            ledger.record_generation_id(identifier, generation_id, source="response")
        return identifier

    def plant(self, status="accepted") -> str:
        """Insert an existing uncertain hold without opening a new ledger or job."""
        identifier = str(uuid4())
        ledger = self.ledger()
        with closing(ledger._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO holds VALUES (?, 0, '2026-10-02', '2026-10', ?, NULL)",
                (identifier, status),
            )
        return identifier

    def confirm(self, identifier, reader, generation_id=None):
        return pilot.confirm_generation_cost(
            self.config, request_id=identifier, generation_id=generation_id, reader=reader,
            evidence_confirmed=generation_id is not None,
        )

    def rows(self):
        with closing(sqlite3.connect(self.path())) as connection:
            refs = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generation_refs'"
            ).fetchone()
            if not refs:
                return [(row[0], row[1], row[2], None, None) for row in connection.execute(
                    "SELECT id, status, actual FROM holds ORDER BY id")]
            return connection.execute(
                "SELECT h.id, h.status, h.actual, g.generation_id, g.source "
                "FROM holds h LEFT JOIN generation_refs g ON g.id=h.id ORDER BY h.id"
            ).fetchall()

    def assert_no_content(self):
        raw = self.path().read_bytes()
        self.assertNotIn(SECRET_TEXT.encode(), raw)
        self.assertNotIn(b"sk-or-synthetic", raw)
        names = sorted(path.name for path in (self.root / "hub").iterdir() if path.is_file())
        self.assertEqual(["free-pilot.sqlite3"], names)

    def test_verified_zero_cost_settles_and_unblocks(self):
        identifier = self.seed(generation_id=GEN)
        reader = Mock(return_value=_body(0))
        result = self.confirm(identifier, reader)
        self.assertEqual("settled", result["status"])
        self.assertTrue(result["cost_verified"])
        self.assertTrue(result["confirmed_now"])
        self.assertFalse(result["retry"])
        self.assertEqual((identifier, "settled", 0, GEN, "response"), self.rows()[0])
        snapshot = operation_status.snapshot(self.config)
        self.assertFalse(snapshot["blocked"])
        self.assertEqual(GEN, snapshot["items"][0]["generation_id"])
        self.assertTrue(snapshot["items"][0]["cost_verified"])
        created = self.ledger().reserve(str(uuid4()), ceiling_usd="0")
        self.assertTrue(created["created"])
        reader.assert_called_once()
        self.lookup.assert_not_called()
        self.chat.assert_not_called()
        self.assert_no_content()

    def test_paid_result_is_overrun_not_zero(self):
        identifier = self.seed(generation_id=GEN)
        result = self.confirm(identifier, Mock(return_value=_body(0.01)))
        self.assertEqual("overrun", result["status"])
        self.assertTrue(result["cost_verified"])
        self.assertTrue(result["confirmed_now"])
        self.assertEqual((identifier, "overrun", 10000, GEN, "response"), self.rows()[0])
        with self.assertRaises(BudgetError):
            self.ledger().reserve(str(uuid4()), ceiling_usd="0")
        self.assertTrue(operation_status.snapshot(self.config)["blocked"])
        self.assert_no_content()

    def test_wrong_id_missing_response_and_timeout_leave_the_hold_unknown(self):
        identifier = self.seed(generation_id=GEN)
        cases = (
            _body(0, OTHER),
            (200, None),
            (200, {}),
            (200, {"data": {"id": GEN}}),
            (200, {"data": {"id": GEN, "total_cost": "0"}}),
            (200, {"data": {"id": GEN, "total_cost": 1e-7}}),
            (404, {"data": {"id": GEN, "total_cost": 0}}),
        )
        for payload in cases:
            reader = Mock(return_value=payload)
            result = self.confirm(identifier, reader)
            self.assertFalse(result["confirmed_now"])
            self.assertFalse(result["cost_verified"])
            self.assertFalse(result["retry"])
            self.assertEqual("unknown", result["status"])
            reader.assert_called_once()
        timed = Mock(side_effect=TimeoutError("private-key"))
        result = self.confirm(identifier, timed)
        self.assertFalse(result["retry"])
        self.assertFalse(result["confirmed_now"])
        self.assertNotIn("private-key", str(result))
        timed.assert_called_once()
        self.assertEqual((identifier, "unknown", None, GEN, "response"), self.rows()[0])
        with self.assertRaises(BudgetError):
            self.ledger().reserve(str(uuid4()), ceiling_usd="0")
        self.lookup.assert_not_called()
        self.assert_no_content()

    def test_same_operation_reconciles_again_without_changing_a_verified_cost(self):
        identifier = self.seed(generation_id=GEN)
        reader = Mock(return_value=_body(0))
        first = self.confirm(identifier, reader)
        second = self.confirm(identifier, reader)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertTrue(second["confirmed_now"])
        self.assertEqual("settled", second["status"])
        reader.return_value = _body(0.02)
        with self.assertRaises(BudgetError):
            self.confirm(identifier, reader)
        self.assertEqual((identifier, "settled", 0, GEN, "response"), self.rows()[0])
        self.assertEqual(1, len(self.rows()))
        self.assertEqual(3, reader.call_count)

    def test_accepted_empty_transitions_only_with_provider_evidence(self):
        first = self.plant()
        second = self.plant()
        untouched = Mock(side_effect=AssertionError("network"))
        skipped = self.confirm(first, untouched)
        self.assertEqual("accepted", skipped["status"])
        self.assertFalse(skipped["cost_verified"])
        untouched.assert_not_called()
        with self.assertRaises(BudgetError):
            self.ledger().reconcile(first, verified_cost_usd="0")
        mismatch = Mock(return_value=_body(0, OTHER))
        denied = self.confirm(first, mismatch, generation_id=GEN)
        self.assertFalse(denied["confirmed_now"])
        self.assertTrue(all(row[3] is None for row in self.rows()))
        timed = Mock(side_effect=TimeoutError("private-key"))
        failed = self.confirm(first, timed, generation_id=GEN)
        self.assertFalse(failed["confirmed_now"])
        self.assertNotIn("private-key", str(failed))
        self.assertIsNone(dict((row[0], row) for row in self.rows())[first][2])
        moved = self.confirm(first, Mock(return_value=_body(0)), generation_id=GEN)
        self.assertEqual("settled", moved["status"])
        self.assertTrue(moved["changed"])
        with self.assertRaises(BudgetError):
            self.ledger().reconcile(second, verified_cost_usd="0")
        with self.assertRaises(BudgetError):
            self.confirm(second, Mock(return_value=_body(0, GEN)), generation_id=GEN)
        self.assertEqual("accepted", dict((row[0], row) for row in self.rows())[second][1])
        self.assertIsNone(dict((row[0], row) for row in self.rows())[second][2])
        charged = self.confirm(second, Mock(return_value=_body(0.01, OTHER)), generation_id=OTHER)
        self.assertEqual("overrun", charged["status"])
        by_id = {row[0]: row for row in self.rows()}
        self.assertEqual((first, "settled", 0, GEN, "evidence"), by_id[first])
        self.assertEqual((second, "overrun", 10000, OTHER, "evidence"), by_id[second])
        self.assertEqual(2, len(by_id))
        with self.assertRaises(BudgetError):
            self.ledger().reserve(str(uuid4()), ceiling_usd="0")
        self.lookup.assert_not_called()
        self.chat.assert_not_called()
        self.assert_no_content()

    def test_unconfirmed_explicit_id_cannot_clear_an_unknown_hold_or_open_another_ledger(self):
        identifier = self.seed()
        reader = Mock(side_effect=AssertionError("network"))
        with self.assertRaises(BudgetError):
            pilot.confirm_generation_cost(self.config, request_id=identifier,
                                          generation_id=GEN, reader=reader)
        reader.assert_not_called()
        self.assertEqual((identifier, "unknown", None, None, None), self.rows()[0])
        absent = SimpleNamespace(data_path=self.root / "empty", auto_publish_enabled=False)
        (self.root / "empty").mkdir(mode=0o700)
        with self.assertRaises(BudgetError):
            pilot.confirm_generation_cost(
                absent, request_id=str(uuid4()), reader=Mock(side_effect=AssertionError("network")),
            )
        self.assertEqual([], list((self.root / "empty").iterdir()))
        self.config.auto_publish_enabled = True
        with self.assertRaises(BudgetError):
            self.confirm(identifier, reader)
        self.assertEqual((identifier, "unknown", None, None, None), self.rows()[0])

    def test_confirmed_legacy_unknown_and_accepted_replays_are_idempotent(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                identifier = self.plant("accepted" if accepted else "unknown")
                generation = "gen-accepted000" if accepted else "gen-unknown0000"
                reader = Mock(return_value=_body(0, generation))
                first = self.confirm(identifier, reader, generation_id=generation)
                second = self.confirm(identifier, reader, generation_id=generation)
                self.assertTrue(first["changed"])
                self.assertFalse(second["changed"])
                self.assertEqual("settled", second["status"])
                self.assertTrue(second["confirmed_now"])
                with self.assertRaises(BudgetError):
                    self.confirm(identifier, reader, generation_id=OTHER)
                self.assertEqual(2, reader.call_count)
        self.chat.assert_not_called()

    def test_new_response_stores_generation_id_without_content_or_lookup(self):
        self.chat.side_effect = None
        self.chat.return_value = (200, {
            "id": GEN, "model": self.model, "usage": {"cost": 0},
            "choices": [{"message": {"content": "NEXUS_FREE_OK"}}], "prompt": SECRET_TEXT,
        })
        with patch.object(pilot.free_model, "read_catalog", return_value=self.catalog):
            result = pilot.run(self.config, request_id=str(uuid4()), model=self.model)
        self.assertEqual(GEN, result["generation_id"])
        self.assertEqual("settled", result["hold_status"])
        self.assertNotIn("output", result)
        self.assertNotIn(SECRET_TEXT, str(result))
        self.lookup.assert_not_called()
        self.assertIn(GEN.encode(), self.path().read_bytes())
        self.assert_no_content()
        uncertain = str(uuid4())
        self.chat.return_value = (200, {
            "id": OTHER, "usage": {"cost": 0.01}, "prompt": SECRET_TEXT,
            "choices": [{"message": {"content": SECRET_TEXT}}],
        })
        with patch.object(pilot.free_model, "read_catalog", return_value=self.catalog):
            pending = pilot.run(self.config, request_id=uncertain, model=self.model)
        self.assertEqual("unknown", pending["hold_status"])
        self.assertIsNone(pending["cost_usd"])
        self.assertNotIn("output", pending)
        self.lookup.assert_not_called()
        row = {item[0]: item for item in self.rows()}[uncertain]
        self.assertEqual(("unknown", None, OTHER, "response"), row[1:])
        checked = complete_free(
            "Synthetic", key="sk-or-synthetic", data_class="synthetic", external_authorized=True,
            model=self.model, catalog_reader=lambda: self.catalog,
            transport=Mock(return_value=(200, {
                "id": "not-a-generation", "usage": {"cost": 0}, "model": self.model,
                "choices": [{"message": {"content": "OK"}}],
            })),
        )
        self.assertNotIn("generation_id", checked)
        self.assert_no_content()

    def test_generation_lookup_uses_fixed_origin_without_content_or_retry(self):
        with patch("nexus.hub.free_model.http.client.HTTPSConnection") as factory:
            response = Mock(status=302, headers={"Location": "https://example.test/generation/content"})
            factory.return_value.getresponse.return_value = response
            self.assertEqual((302, None), read_generation("sk-or-synthetic", GEN))
            factory.assert_called_once_with("openrouter.ai", timeout=8)
            requested = factory.return_value.request.call_args
            self.assertEqual("GET", requested.args[0])
            self.assertEqual("/api/v1/generation?id=" + GEN, requested.args[1])
            self.assertNotIn("content", requested.args[1])
            response.read.assert_not_called()
            factory.return_value.request.assert_called_once()
            factory.return_value.close.assert_called_once()
            factory.reset_mock()
            with self.assertRaises(BudgetError):
                read_generation("sk-or-synthetic", "gen-short")
            with self.assertRaises(BudgetError):
                read_generation("not-a-key", GEN)
            factory.assert_not_called()


@skipIf(FastAPI is None, "FastAPI is supplied by the Hermes runtime")
class GenerationCostApiTests(TestCase):
    def test_http_evidence_flow_reopens_the_real_temporary_ledger(self):
        path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location("nexus_generation_cost_integration_test", path)
        module = importlib.util.module_from_spec(spec)
        self.enterContext(patch.dict(sys.modules, {spec.name: module}))
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router)
        with TemporaryDirectory(dir=Path(gettempdir()).resolve()) as directory:
            config = SimpleNamespace(data_path=Path(directory), auto_publish_enabled=False)
            folder = config.data_path / "hub"
            folder.mkdir(mode=0o700)
            ledger = PilotBudget(folder / "free-pilot.sqlite3", per_job_usd="0",
                                 daily_usd="0", monthly_usd="0")
            identifier = str(uuid4())
            ledger.reserve(identifier, ceiling_usd="0")
            ledger.reconcile(identifier, verified_cost_usd=None)
            with patch.object(module, "_settings", return_value=config), \
                 patch.object(module._pilot.providers, "_credentials", return_value={"api_key": "sk-or-synthetic"}), \
                 patch.object(module._pilot.free_model, "read_generation", return_value=_body(0, OTHER)) as lookup, \
                 patch.object(module._pilot.free_model, "_transport", side_effect=AssertionError("inference")) as chat, \
                 TestClient(app) as client:
                url = "/hub/generation-cost?profile=default"
                body = {"request_id": identifier, "generation_id": GEN}
                self.assertEqual(409, client.post(url, json=body).status_code)
                lookup.assert_not_called()
                body["evidence_confirmed"] = True
                self.assertFalse(client.post(url, json=body).json()["confirmed_now"])
                self.assertTrue(operation_status.snapshot(config)["blocked"])
                lookup.return_value = _body(0)
                first = client.post(url, json=body)
                self.assertEqual(200, first.status_code)
                self.assertTrue(first.json()["changed"])
                repeated = client.post(url, json=body)
                self.assertEqual(200, repeated.status_code)
                self.assertFalse(repeated.json()["changed"])
                self.assertFalse(operation_status.snapshot(config)["blocked"])
                self.assertEqual(1, operation_status.snapshot(config)["total"])
                chat.assert_not_called()

    def test_route_is_explicit_and_rejects_extra_content(self):
        path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location("nexus_generation_cost_api_test", path)
        module = importlib.util.module_from_spec(spec)
        self.enterContext(patch.dict(sys.modules, {spec.name: module}))
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router)
        identifier = str(uuid4())
        with patch.object(module._pilot, "confirm_generation_cost",
                          return_value={"status": "unknown", "cost_verified": False,
                                        "retry": False}) as confirm, \
             patch.object(module, "_settings", return_value=object()), TestClient(app) as client:
            base = "/hub/generation-cost"
            self.assertEqual(405, client.get(base + "?profile=default").status_code)
            self.assertEqual(422, client.post(base).status_code)
            self.assertEqual(409, client.post(base, json={"request_id": identifier}).status_code)
            self.assertEqual(409, client.post(base + "?profile=other",
                                              json={"request_id": identifier}).status_code)
            self.assertEqual(422, client.post(base + "?profile=default", json={
                "request_id": identifier, "prompt": SECRET_TEXT,
            }).status_code)
            self.assertEqual(422, client.post(base + "?profile=default", json={
                "request_id": identifier, "evidence_confirmed": "true",
            }).status_code)
            confirm.assert_not_called()
            response = client.post(base + "?profile=default", json={"request_id": identifier})
            self.assertEqual(200, response.status_code)
            self.assertEqual("no-store", response.headers["cache-control"])
            confirm.assert_called_once()
            self.assertEqual(identifier, confirm.call_args.kwargs["request_id"])
            self.assertIsNone(confirm.call_args.kwargs["generation_id"])
            self.assertFalse(confirm.call_args.kwargs["evidence_confirmed"])
