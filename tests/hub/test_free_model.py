from unittest import TestCase
from unittest.mock import Mock, patch

from nexus.hub.budget import BudgetError
from nexus.hub.free_model import _transport, build_request, complete_free


class FreeModelTests(TestCase):
    def call(self, transport, **kwargs):
        return complete_free("Synthetic test", key="sk-or-synthetic", data_class="synthetic",
                             external_authorized=True, transport=transport, **kwargs)

    def test_request_pins_free_router_zero_prices_and_no_fallback(self):
        body = build_request("Synthetic test", data_class="synthetic", external_authorized=True)
        self.assertEqual("openrouter/free", body["model"])
        self.assertEqual(64, body["max_tokens"])
        self.assertEqual("deny", body["provider"]["data_collection"])
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertTrue(body["provider"]["require_parameters"])
        self.assertTrue(all(v == 0 for v in body["provider"]["max_price"].values()))
        for field in ("models", "tools", "plugins", "route"):
            self.assertNotIn(field, body)

    def test_paid_and_misnamed_free_models_never_call_transport(self):
        transport = Mock(side_effect=AssertionError("network"))
        for model in ("openrouter/auto", "openrouter/auto:free", "vendor/paid", "vendor/model:free"):
            with self.assertRaises(BudgetError):
                self.call(transport, model=model)
        transport.assert_not_called()

    def test_private_data_or_missing_permission_never_calls_transport(self):
        transport = Mock(side_effect=AssertionError("network"))
        for data in ("sensitive", "local_only", "undetermined"):
            with self.assertRaises(BudgetError):
                complete_free("Synthetic", key="sk-or-synthetic", data_class=data,
                              external_authorized=True, transport=transport)
        with self.assertRaises(BudgetError):
            complete_free("Synthetic", key="sk-or-synthetic", data_class="synthetic",
                          external_authorized=False, transport=transport)
        transport.assert_not_called()

    def test_invalid_key_and_oversize_text_never_call_transport(self):
        transport = Mock(side_effect=AssertionError("network"))
        for text, key in (("x" * 501, "sk-or-synthetic"), ("x", ""),
                          ("x", "sk-or-bad\nkey")):
            with self.assertRaises(BudgetError):
                complete_free(text, key=key, data_class="synthetic",
                              external_authorized=True, transport=transport)
        transport.assert_not_called()

    def test_http_failure_stops_once_without_fallback_or_error_leak(self):
        for status in (302, 401, 402, 429, 503):
            transport = Mock(return_value=(status, {"error": "private-key"}))
            result = self.call(transport)
            self.assertEqual("stopped", result["status"])
            self.assertEqual(status, result["http_status"])
            self.assertFalse(result["retry"])
            self.assertNotIn("private-key", str(result))
            transport.assert_called_once()

    def test_timeout_is_unknown_not_free_or_safe_to_retry(self):
        result = self.call(Mock(side_effect=TimeoutError("private-key")))
        self.assertEqual("unknown", result["status"])
        self.assertFalse(result["cost_verified"])
        self.assertFalse(result["retry"])
        self.assertNotIn("private-key", str(result))

    def test_only_explicit_numeric_zero_cost_is_verified(self):
        for cost in (None, True, "0", 0.01, float("nan")):
            result = self.call(Mock(return_value=(200, {"usage": {"cost": cost}})))
            self.assertEqual("needs_reconciliation", result["status"])
        result = self.call(Mock(return_value=(200, {
            "usage": {"cost": 0}, "model": "synthetic/free-model",
            "choices": [{"message": {"content": "OK"}}],
        })))
        self.assertEqual("completed", result["status"])
        self.assertEqual(0, result["cost_usd"])

    def test_transport_has_fixed_tls_origin_and_no_redirect_or_retry(self):
        with patch("nexus.hub.free_model.http.client.HTTPSConnection") as factory:
            response = Mock(status=302)
            factory.return_value.getresponse.return_value = response
            self.assertEqual((302, None), _transport("sk-or-synthetic", {}))
            factory.assert_called_once_with("openrouter.ai", timeout=20)
            response.read.assert_not_called()
            factory.return_value.close.assert_called_once()
