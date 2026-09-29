from __future__ import annotations

import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from nexus.hub.providers import ProviderUsageError, _credentials, _read_key, snapshot


class ProviderUsageTests(unittest.TestCase):
    def test_credentials_use_scoped_secret_and_readonly_config_without_pool_loader(self):
        for model, names in (
            ({}, ["OPENROUTER_API_KEY"]),
            ({"provider": "openrouter", "key_env": "CUSTOM_KEY"}, ["CUSTOM_KEY"]),
            ({"provider": "other", "key_env": "OTHER_KEY"}, ["OPENROUTER_API_KEY"]),
        ):
            getter = Mock(return_value="synthetic-key")
            config = Mock(return_value={"model": model})
            with patch.dict(sys.modules, {
                "agent.secret_scope": SimpleNamespace(get_secret=getter),
                "hermes_cli.config": SimpleNamespace(load_config_readonly=config),
                "agent.credential_pool": SimpleNamespace(
                    load_pool=Mock(side_effect=AssertionError("pool migration"))),
            }):
                self.assertEqual({"api_key": "synthetic-key"}, _credentials("openrouter"))
                self.assertEqual(names, [call.args[0] for call in getter.call_args_list])
                config.assert_called_once()

    def run_snapshot(self, data):
        return snapshot("openrouter", resolve=lambda _: {"api_key": "synthetic-key"},
                        transport=lambda _: (200, {"data": data}))

    def test_whitelists_metrics_and_never_exposes_identity(self):
        result = self.run_snapshot({
            "usage": 3.2, "usage_daily": 0, "limit": 10, "limit_remaining": 6.8,
            "label": "synthetic-key", "creator_user_id": "private-user",
            "workspace_id": "private-workspace", "limit_reset": "monthly",
        })
        self.assertEqual("available", result["status"])
        self.assertEqual(0, result["metrics"]["usage_daily"])
        self.assertEqual(6.8, result["metrics"]["limit_remaining"])
        self.assertIsNone(result["metrics"]["usage_weekly"])
        self.assertEqual("monthly", result["limit_reset"])
        self.assertFalse(result["inference_called"])
        self.assertEqual("current_key", result["scope"])
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("synthetic-key", json.dumps(result))

    def test_missing_metrics_are_unknown_not_zero_or_unlimited(self):
        result = self.run_snapshot({})
        self.assertEqual("unknown", result["status"])
        self.assertTrue(all(v is None for v in result["metrics"].values()))

    def test_bad_numbers_and_reset_are_not_forwarded(self):
        for value in (True, -1, "2", float("inf"), float("nan"), 10 ** 400):
            with self.subTest(value=type(value).__name__):
                result = self.run_snapshot({"usage": value, "limit_reset": "private-label"})
                self.assertIsNone(result["metrics"]["usage"])
                self.assertIsNone(result["limit_reset"])

    def test_missing_or_invalid_key_does_not_call_transport(self):
        for key in (None, "", "bad\r\nkey", "non-ascii-ş", 123):
            transport = Mock(side_effect=AssertionError("external call"))
            result = snapshot("openrouter", resolve=lambda _: {"api_key": key},
                              transport=transport)
            transport.assert_not_called()
            self.assertIsNone(result["metrics"])

    def test_secret_resolver_exception_is_sanitized(self):
        result = snapshot("openrouter", resolve=Mock(side_effect=RuntimeError("private-key")))
        self.assertEqual("credentials_unavailable", result["status"])
        self.assertNotIn("private-key", json.dumps(result))

    def test_unsupported_provider_does_not_resolve_secrets(self):
        resolve = Mock(side_effect=AssertionError("secret read"))
        with self.assertRaises(ProviderUsageError):
            snapshot("custom-url", resolve=resolve)
        resolve.assert_not_called()

    def test_other_providers_are_honestly_unavailable_without_network_or_secret(self):
        for provider in ("gemini", "nvidia", "antigravity"):
            resolve = Mock(side_effect=AssertionError("secret read"))
            transport = Mock(side_effect=AssertionError("external call"))
            result = snapshot(provider, resolve=resolve, transport=transport)
            self.assertEqual("unavailable", result["status"])
            self.assertIsNone(result["metrics"])
            resolve.assert_not_called()
            transport.assert_not_called()

    def test_management_key_is_not_treated_as_model_budget(self):
        for field in ("is_management_key", "is_provisioning_key"):
            result = self.run_snapshot({field: True, "limit_remaining": 100})
            self.assertEqual("unsupported_key", result["status"])
            self.assertIsNone(result["metrics"])

    def test_error_statuses_are_sanitized_without_retry(self):
        for code, status in ((401, "unauthorized"), (403, "unauthorized"),
                             (429, "rate_limited"), (302, "unavailable"), (500, "unavailable")):
            transport = Mock(return_value=(code, {"error": "private-key"}))
            result = snapshot("openrouter", resolve=lambda _: {"api_key": "synthetic-key"},
                              transport=transport)
            self.assertEqual(status, result["status"])
            self.assertNotIn("private-key", json.dumps(result))
            transport.assert_called_once()

    def test_bad_payloads_and_transport_exceptions_do_not_escape(self):
        for payload in (None, [], {"data": []}):
            result = snapshot("openrouter", resolve=lambda _: {"api_key": "synthetic-key"},
                              transport=lambda _: (200, payload))
            self.assertEqual("unavailable", result["status"])
        result = snapshot("openrouter", resolve=lambda _: {"api_key": "synthetic-key"},
                          transport=Mock(side_effect=TimeoutError("private-key")))
        self.assertNotIn("private-key", json.dumps(result))
        self.assertEqual("unavailable", result["status"])

    def test_http_transport_has_fixed_tls_origin_timeout_and_bounded_read(self):
        response = Mock(status=200)
        response.read.return_value = b'{"data":{"usage":1}}'
        with patch("nexus.hub.providers.http.client.HTTPSConnection") as factory:
            connection = factory.return_value
            connection.getresponse.return_value = response
            status, payload = _read_key("synthetic-key")
            factory.assert_called_once_with("openrouter.ai", timeout=8)
            connection.request.assert_called_once_with("GET", "/api/v1/key", headers={
                "Authorization": "Bearer synthetic-key", "Accept": "application/json",
            })
            response.read.assert_called_once_with(32769)
            connection.close.assert_called_once()
            self.assertEqual(200, status)
            self.assertEqual(1, payload["data"]["usage"])

    def test_redirect_is_not_followed_or_body_read(self):
        response = Mock(status=302)
        with patch("nexus.hub.providers.http.client.HTTPSConnection") as factory:
            factory.return_value.getresponse.return_value = response
            self.assertEqual((302, None), _read_key("synthetic-key"))
            response.read.assert_not_called()
            factory.assert_called_once()
            factory.return_value.close.assert_called_once()

    def test_oversized_response_closes_connection(self):
        response = Mock(status=200)
        response.read.return_value = b"x" * 32769
        with patch("nexus.hub.providers.http.client.HTTPSConnection") as factory:
            factory.return_value.getresponse.return_value = response
            with self.assertRaises(ValueError):
                _read_key("synthetic-key")
            factory.return_value.close.assert_called_once()
