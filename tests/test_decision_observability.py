from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from nexus.config import NexusConfig
from nexus.decision import RouteCategory, route_text
from nexus.decision.hook import build_pre_llm_handler
from nexus.decision.observability import (
    CircuitBreaker,
    RouteLogEntry,
    append_jsonl,
    log_route_report,
)
from nexus.errors import DecisionError


def _config(**overrides: object) -> NexusConfig:
    values: dict[str, object] = {}
    values.update(overrides)
    return NexusConfig.from_mapping(values)


class RouteLogEntryTests(unittest.TestCase):
    def test_entry_dict_has_no_raw_text(self) -> None:
        entry = RouteLogEntry(
            ts="2026-09-21T09:00:00+03:00",
            intent="chat",
            confidence=0.98,
            latency_ms=45,
            success=True,
            backend="classifier.dev",
            classifier_invoked=True,
            llm_fallback_invoked=False,
            needs_human_review=False,
            review_band="high_confidence",
            reason_codes=("classifier_prediction",),
            text_len=25,
            preview="",
        )
        data = entry.to_dict()
        self.assertNotIn("raw_text", data)
        self.assertEqual(25, data["text_length"])
        self.assertEqual("", data["preview"])

    def test_preview_is_capped(self) -> None:
        from nexus.decision.observability import _privacy_preview

        preview = _privacy_preview("sifre 123456 super secret deger " * 10)
        self.assertLessEqual(len(preview), 48)


class JsonlWriterTests(unittest.TestCase):
    def test_append_and_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs" / "classifier.jsonl"
            entry = RouteLogEntry(
                ts="2026-09-21T09:00:00+03:00",
                intent="task",
                confidence=0.9,
                latency_ms=10,
                success=True,
                backend="local_rules",
                classifier_invoked=False,
                llm_fallback_invoked=False,
                needs_human_review=False,
                review_band="high_confidence",
                reason_codes=("local_reminder_term",),
                text_len=10,
                preview="",
            )
            self.assertTrue(append_jsonl(path, entry))
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(1, len(rows))
            self.assertEqual("task", rows[0]["intent"])
            self.assertEqual(10, rows[0]["latency_ms"])

    def test_rotation_keeps_one_sibling(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classifier.jsonl"
            tiny = RouteLogEntry(
                ts="t",
                intent="chat",
                confidence=1.0,
                latency_ms=1,
                success=True,
                backend="local_rules",
                classifier_invoked=False,
                llm_fallback_invoked=False,
                needs_human_review=False,
                review_band="high_confidence",
                reason_codes=(),
                text_len=0,
                preview="",
            )
            # First fill a file past the rotation size using the env override path
            import nexus.decision.observability as obs

            old = obs._MAX_BYTES
            try:
                obs._MAX_BYTES = 600
                # append_jsonl reads the module global at call time
                for _ in range(6):
                    append_jsonl(path, tiny)
            finally:
                obs._MAX_BYTES = old
            self.assertTrue(path.exists())
            rotated = path.with_name(path.name + ".1")
            self.assertTrue(rotated.exists())

    def test_failure_returns_false_never_raises(self) -> None:
        # A directory where the file should be forces the open() to fail.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "classifier.jsonl"
            path.mkdir()
            entry = RouteLogEntry(
                ts="t",
                intent="chat",
                confidence=1.0,
                latency_ms=1,
                success=True,
                backend="local_rules",
                classifier_invoked=False,
                llm_fallback_invoked=False,
                needs_human_review=False,
                review_band="high_confidence",
                reason_codes=(),
                text_len=0,
                preview="",
            )
            self.assertFalse(append_jsonl(path, entry))

    def test_log_route_report_from_decision_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs" / "classifier.jsonl"
            report = route_text("nasılsın", _config())
            self.assertTrue(
                log_route_report(
                    path, report, latency_ms=42, success=True, text="nasılsın"
                )
            )
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(1, len(rows))
            self.assertEqual("chat", rows[0]["intent"])
            self.assertEqual(42, rows[0]["latency_ms"])
            self.assertEqual("", rows[0]["preview"])
            self.assertNotIn("nasılsın", path.read_text())


class CircuitBreakerTests(unittest.TestCase):
    def test_opens_after_consecutive_failures(self) -> None:
        now = {"t": 0.0}

        def clock() -> float:
            return now["t"]

        breaker = CircuitBreaker(failure_limit=3, cooldown_seconds=300.0, clock=clock)
        self.assertTrue(breaker.allow_external())
        breaker.record_failure()
        breaker.record_failure()
        self.assertTrue(breaker.allow_external())
        breaker.record_failure()
        self.assertFalse(breaker.allow_external())  # open
        self.assertTrue(breaker.is_open)

        now["t"] = 301.0
        self.assertTrue(breaker.allow_external())  # cooldown elapsed

    def test_success_resets_ladder(self) -> None:
        breaker = CircuitBreaker(failure_limit=3, cooldown_seconds=300.0)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        # Third consecutive failure after reset trips the breaker
        breaker.record_failure()
        self.assertTrue(breaker.is_open)

    def test_breaker_degrades_router_to_local_rules(self) -> None:
        calls: list[object] = []

        def runner(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))
            raise AssertionError("classifier must not run while breaker is open")

        breaker = CircuitBreaker(failure_limit=1, cooldown_seconds=300.0)
        breaker.record_failure()  # open the breaker

        report = route_text(
            "Bugünkü yapay zeka haberlerini araştır.",
            _config(decision_classifier_enabled=True),
            classifier_runner=runner,
            breaker=breaker,
        )
        self.assertEqual([], calls)
        self.assertEqual("local_rules", report.backend)
        self.assertIn("classifier_breaker_open", report.reason_codes)
        self.assertFalse(report.to_dict()["would_execute"])

    def test_failures_are_counted_and_trip_breaker_via_router(self) -> None:
        breaker = CircuitBreaker(failure_limit=2, cooldown_seconds=300.0)
        cfg = _config(decision_classifier_enabled=True)
        for _ in range(2):
            with self.assertRaises(DecisionError):
                route_text(
                    "asdf123",
                    cfg,
                    classifier_runner=lambda *a, **k: (_ for _ in ()).throw(
                        DecisionError("classifier invocation failed")
                    ),
                    breaker=breaker,
                )
        self.assertTrue(breaker.is_open)
        # Now the router degrades instead of raising
        report = route_text("asdf123", cfg, breaker=breaker)
        self.assertEqual("local_rules", report.backend)


class HookLoggingTests(unittest.TestCase):
    def _ctx(self, tmp: str, **overrides: object) -> SimpleNamespace:
        values = {
            "vault_path": "/tmp/vault-does-not-exist-for-route",
            "data_path": tmp,
            "decision_classifier_enabled": False,
            "decision_log_enabled": True,
            "decision_log_preview": False,
        }
        values.update(overrides)

        def get_config(key: str, default: object = None) -> object:
            if key in values:
                return values[key]
            return default

        return SimpleNamespace(get_config=get_config, llm=None)

    def test_hook_writes_jsonl_and_never_blocks_turn(self) -> None:
        from nexus.decision.hook import build_pre_llm_handler

        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(tmp)
            handler = build_pre_llm_handler(ctx)
            result = handler(user_message="Merhaba Hermes nasılsın?")
            # Sessiz shadow: kullanıcıya görünür context yok
            self.assertIsNone(result)
            log_path = Path(tmp) / "logs" / "classifier.jsonl"
            self.assertTrue(log_path.exists())
            rows = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertEqual(1, len(rows))
            self.assertEqual("chat", rows[0]["intent"])
            # raw text never persisted without preview opt-in
            self.assertNotIn("nasılsın", log_path.read_text())

    def test_hook_logs_failure_row_when_route_raises(self) -> None:
        import unittest.mock as mock

        from nexus.decision import hook as hook_mod

        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(tmp, decision_classifier_enabled=True)
            handler = build_pre_llm_handler(ctx)
            with mock.patch.object(
                hook_mod,
                "route_text",
                side_effect=DecisionError("classifier invocation failed"),
            ):
                result = handler(user_message="asdf123")
            self.assertIsNone(result)  # fail-open: turn continues
            log_path = Path(tmp) / "logs" / "classifier.jsonl"
            self.assertTrue(log_path.exists())
            rows = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertEqual(1, len(rows))
            self.assertFalse(rows[0]["success"])

    def test_hook_log_disabled_writes_nothing(self) -> None:
        from nexus.decision.hook import build_pre_llm_handler

        with tempfile.TemporaryDirectory() as tmp:
            ctx = self._ctx(tmp, decision_log_enabled=False)
            handler = build_pre_llm_handler(ctx)
            self.assertIsNone(handler(user_message="nasılsın"))
            log_path = Path(tmp) / "logs" / "classifier.jsonl"
            self.assertFalse(log_path.exists())


if __name__ == "__main__":
    unittest.main()