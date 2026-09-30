from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from nexus.hub import pilot
from nexus.hub.budget import BudgetError


class PilotTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=Path(gettempdir()).resolve())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(data_path=self.root, auto_publish_enabled=False)
        self.model = "stealth/space-bunny-alpha"
        self.catalog = {"data": [{"id": self.model, "pricing": {"prompt": "0", "completion": "0"}}]}
        self.reader = self.enterContext(patch.object(pilot.free_model, "read_catalog", return_value=self.catalog))
        self.secret = self.enterContext(patch.object(pilot.providers, "_credentials", return_value={"api_key": "sk-or-synthetic"}))
        self.transport = self.enterContext(patch.object(pilot.free_model, "_transport", return_value=(200, {
            "model": self.model, "usage": {"cost": 0},
            "choices": [{"message": {"content": "NEXUS_FREE_OK"}}],
        })))

    def run_pilot(self, identifier=None, model=None):
        return pilot.run(self.config, request_id=identifier or str(uuid4()), model=model or self.model)

    def test_fixed_prompt_and_zero_cost_evidence_without_returning_content_or_secret(self):
        result = self.run_pilot()
        self.assertEqual("completed", result["status"])
        self.assertTrue(result["expected_output"])
        self.assertEqual("settled", result["hold_status"])
        self.assertEqual(0, result["cost_usd"])
        self.assertNotIn("sk-or-synthetic", str(result))
        self.assertNotIn("output", result)
        body = self.transport.call_args.args[1]
        self.assertEqual(pilot.PROMPT, body["messages"][0]["content"])
        self.assertFalse(body["provider"]["allow_fallbacks"])

    def test_same_id_never_dispatches_twice(self):
        identifier = str(uuid4())
        self.run_pilot(identifier)
        result = self.run_pilot(identifier)
        self.assertEqual("already_recorded", result["status"])
        self.assertFalse(result["inference_attempted"])
        self.transport.assert_called_once()

    def test_unknown_result_blocks_new_job_even_after_reopening(self):
        self.transport.side_effect = TimeoutError("private-error")
        result = self.run_pilot()
        self.assertEqual("unknown", result["hold_status"])
        self.assertNotIn("private-error", str(result))
        with self.assertRaises(BudgetError):
            self.run_pilot()
        self.transport.assert_called_once()

    def test_invalid_model_id_or_publish_setting_does_not_read_key_or_call_network(self):
        for identifier, model in (("bad", self.model), (str(uuid4()), "vendor/paid")):
            with self.assertRaises(BudgetError):
                pilot.run(self.config, request_id=identifier, model=model)
        self.config.auto_publish_enabled = True
        with self.assertRaises(BudgetError):
            self.run_pilot()
        self.reader.assert_not_called()
        self.secret.assert_not_called()
        self.transport.assert_not_called()
        self.assertFalse((self.root / "hub").exists())

    def test_missing_key_or_changed_price_do_not_create_ledger(self):
        self.secret.return_value = {"api_key": ""}
        with self.assertRaises(BudgetError):
            self.run_pilot()
        self.catalog["data"][0]["pricing"]["prompt"] = "0.1"
        with self.assertRaises(BudgetError):
            self.run_pilot()
        self.transport.assert_not_called()
        self.assertFalse((self.root / "hub").exists())

    def test_catalog_failure_does_not_create_ledger_or_send_inference(self):
        self.reader.side_effect = TimeoutError("catalog")
        with self.assertRaises(TimeoutError):
            self.run_pilot()
        self.transport.assert_not_called()
        self.assertFalse((self.root / "hub").exists())

    def test_summary_requires_explicit_consent_and_bounded_text_before_network(self):
        for consent, safe, text in ((False, True, "metin"), (True, False, "metin"),
                                    ("true", True, "metin"), (True, True, ""),
                                    (True, True, "a" * 401)):
            with self.assertRaises(BudgetError):
                pilot.summarize(self.config, request_id=str(uuid4()), model=self.model,
                                text=text, external_authorized=consent, non_sensitive=safe)
        self.reader.assert_not_called()
        self.secret.assert_not_called()
        self.transport.assert_not_called()
        self.assertFalse((self.root / "hub").exists())

    def test_summary_returns_transient_draft_and_never_saves_content(self):
        text = "sentetik-secilen-metin"
        output = "sentetik-ozet-yaniti"
        self.transport.return_value[1]["choices"][0]["message"]["content"] = output
        identifier = str(uuid4())
        result = pilot.summarize(self.config, request_id=identifier, model=self.model,
                                 text=text, external_authorized=True, non_sensitive=True)
        self.assertEqual(output, result["output"])
        body = self.transport.call_args.args[1]
        self.assertTrue(body["messages"][0]["content"].endswith(text))
        self.assertLessEqual(len(body["messages"][0]["content"]), 500)
        self.assertFalse(body["provider"]["allow_fallbacks"])
        for file in self.root.rglob("*"):
            if file.is_file():
                raw = file.read_bytes()
                self.assertNotIn(text.encode(), raw)
                self.assertNotIn(output.encode(), raw)
        again = pilot.summarize(self.config, request_id=identifier, model=self.model,
                                text=text, external_authorized=True, non_sensitive=True)
        self.assertEqual("already_recorded", again["status"])
        self.assertNotIn("output", again)
        self.transport.assert_called_once()

    def test_summary_unknown_cost_never_returns_output_or_retries(self):
        self.transport.return_value[1]["usage"] = {}
        result = pilot.summarize(self.config, request_id=str(uuid4()), model=self.model,
                                 text="sentetik", external_authorized=True, non_sensitive=True)
        self.assertEqual("unknown", result["hold_status"])
        self.assertNotIn("output", result)
        with self.assertRaises(BudgetError):
            pilot.summarize(self.config, request_id=str(uuid4()), model=self.model,
                            text="sentetik", external_authorized=True, non_sensitive=True)
        self.transport.assert_called_once()
