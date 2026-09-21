from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from nexus.config import NexusConfig
from nexus.decision import RouteCategory, route_text
from nexus.decision.classifier import predict_with_classifier
from nexus.errors import ConfigurationError, DecisionError
from nexus.policy import Sensitivity


def _config(**overrides: object) -> NexusConfig:
    values: dict[str, object] = {}
    values.update(overrides)
    return NexusConfig.from_mapping(values)


class DecisionRouterTests(unittest.TestCase):
    def test_high_risk_command_never_executes_or_calls_classifier(self) -> None:
        calls: list[object] = []

        def runner(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))
            raise AssertionError("classifier must not run")

        report = route_text(
            "Mac mini'yi yeniden başlat ve Hermes'i aç",
            _config(decision_classifier_enabled=True),
            classifier_runner=runner,
        )

        self.assertEqual(RouteCategory.COMMAND, report.category)
        self.assertEqual(1.0, report.confidence)
        self.assertEqual("local_rules", report.backend)
        self.assertFalse(report.external_classifier_invoked)
        self.assertFalse(report.to_dict()["would_execute"])
        self.assertTrue(report.to_dict()["needs_human_review"])
        self.assertIn("high_risk_command", report.reason_codes)
        self.assertIn("external_classifier_blocked", report.reason_codes)
        self.assertEqual([], calls)

    def test_sensitive_customer_text_is_not_sent_to_classifier(self) -> None:
        def runner(*args: object, **kwargs: object) -> None:
            raise AssertionError("classifier must not run")

        report = route_text(
            "Müşteri yarın pasaportunu getirecek",
            _config(decision_classifier_enabled=True),
            classifier_runner=runner,
        )

        self.assertEqual(RouteCategory.CUSTOMER_OR_CRM, report.category)
        self.assertEqual(Sensitivity.LEGAL_IDENTITY, report.sensitivity)
        self.assertFalse(report.external_classifier_invoked)
        self.assertIn("external_classifier_blocked", report.reason_codes)
        self.assertNotIn("pasaport", json.dumps(report.to_dict()))

    def test_local_chat_does_not_write_or_enforce_confidence_policy(self) -> None:
        report = route_text("Bugün hava çok güzel ya", _config())
        payload = report.to_dict()

        self.assertEqual(RouteCategory.CHAT, report.category)
        self.assertEqual("local_rules", report.backend)
        self.assertFalse(payload["writes_performed"])
        self.assertFalse(payload["candidate_policy"]["enforced"])
        self.assertEqual(0.85, payload["candidate_policy"]["high_confidence"])
        self.assertEqual(0.6, payload["candidate_policy"]["low_risk_min"])

    def test_secret_like_value_blocks_external_backends(self) -> None:
        report = route_text(
            "api_key = sk_abcdefghijklmnop1234",
            _config(decision_llm_fallback_enabled=True),
            llm=SimpleNamespace(complete_structured=lambda **kwargs: None),
        )
        self.assertEqual(RouteCategory.UNKNOWN, report.category)
        self.assertEqual(Sensitivity.CREDENTIAL, report.sensitivity)
        self.assertFalse(report.llm_fallback_invoked)
        self.assertIn("secret_like_value", report.reason_codes)

    def test_mocked_classifier_uses_stdin_and_omits_source_text(self) -> None:
        captured: dict[str, object] = {}

        def runner(command, **kwargs):
            captured["command"] = command
            captured["input"] = kwargs["input"]
            captured["env"] = kwargs["env"]
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps(
                    {"label": "chat", "confidence": 0.91, "text": "must-not-leak"}
                )
                + "\n",
            )

        report = route_text(
            "Bugün hava çok güzel ya",
            _config(decision_classifier_enabled=True),
            classifier_runner=runner,
        )
        payload = json.dumps(report.to_dict())

        self.assertTrue(report.external_classifier_invoked)
        self.assertEqual(RouteCategory.CHAT, report.category)
        self.assertEqual(0.91, report.confidence)
        self.assertEqual("classifier.dev", report.backend)
        self.assertEqual("--json", captured["command"][2])
        self.assertNotIn("Bugün hava çok güzel ya", " ".join(str(part) for part in captured["command"]))
        self.assertNotIn("CLASSIFY_API_KEY", captured["env"])
        self.assertNotIn("must-not-leak", payload)

    def test_llm_fallback_is_tool_free_and_fenced(self) -> None:
        seen: dict[str, object] = {}

        class Llm:
            def complete_structured(self, **kwargs):
                seen.update(kwargs)
                return SimpleNamespace(
                    parsed={"category": "task", "confidence": 0.4},
                    text="",
                )

        report = route_text(
            "Raporu akşama kadar bitirmem lazım",
            _config(decision_llm_fallback_enabled=True),
            llm=Llm(),
        )

        self.assertTrue(report.llm_fallback_invoked)
        self.assertEqual(RouteCategory.TASK, report.category)
        self.assertEqual("nexus_route", seen["task"])
        self.assertTrue(str(seen["input"][0]["text"]).startswith("UNTRUSTED_DATA_JSON"))

    def test_classifier_adapter_rejects_unknown_labels(self) -> None:
        def runner(*args: object, **kwargs: object):
            return SimpleNamespace(returncode=0, stdout='{"label": "spam", "confidence": 1}\n')

        with self.assertRaises(DecisionError):
            predict_with_classifier("hello", executable="classify", runner=runner)

    def test_empty_text_fails_closed(self) -> None:
        with self.assertRaises(DecisionError):
            route_text("  ", _config())

    def test_candidate_thresholds_must_stay_ordered(self) -> None:
        with self.assertRaises(ConfigurationError):
            _config(decision_high_confidence=0.5, decision_low_risk_min=0.8)


if __name__ == "__main__":
    unittest.main()
