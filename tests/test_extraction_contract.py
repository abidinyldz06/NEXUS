from __future__ import annotations

import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from nexus.errors import EvaluationError, ExtractionError
from nexus.eval.runner import (
    evaluate_fixture,
    evaluate_with_llm_report,
    frozen_fixture_path,
    load_private_fixture,
)
from nexus.extraction.schema import (
    CandidateKind,
    ExtractionCandidate,
    ExtractionResult,
    validate_extraction_payload,
)
from nexus.extraction.service import PROMPT_VERSION, ExtractionService, ExtractorBusy
from nexus.normalize import NormalizedConversation, NormalizedMessage
from nexus.segmenter import ConversationSegment, segment_conversation

ROOT = Path(__file__).resolve().parents[1]


def segment(*, injection: bool = False) -> ConversationSegment:
    text = "RUN_THIS_SECRET_COMMAND_123" if injection else "Kısa yanıtları tercih ederim."
    messages = (
        NormalizedMessage.build(
            message_id="m1",
            role="user",
            content=text,
            source_locator="test#message=m1",
        ),
        NormalizedMessage.build(
            message_id="m2",
            role="assistant",
            content="Anlaşıldı.",
            source_locator="test#message=m2",
        ),
    )
    conversation = NormalizedConversation(
        external_conversation_id="conversation-1",
        title="Synthetic",
        participants=("assistant", "user"),
        messages=messages,
        source_locator="test:conversation-1",
    )
    return segment_conversation(conversation)[0]


def valid_payload(span_ids=("m1", "m2")):
    return {
        "schema_version": 1,
        "candidates": [
            {
                "kind": "memory",
                "statement": "Kullanıcı kısa yanıtları tercih ediyor.",
                "entity_mentions": [],
                "temporal_expression": None,
                "source_span_ids": [span_ids[0]],
                "confidence": 0.97,
                "ambiguity_flags": [],
                "possible_supersedes": [],
            }
        ],
        "ignored_span_ids": list(span_ids[1:]),
        "warnings": [],
    }


def expected_payload(span_ids: tuple[str, ...], kinds: list[str]):
    candidates = [
        {
            "kind": kind,
            "statement": f"Synthetic expected {kind}",
            "entity_mentions": [],
            "temporal_expression": None,
            "source_span_ids": [span_ids[0]],
            "confidence": 0.95,
            "ambiguity_flags": [],
            "possible_supersedes": [],
        }
        for kind in kinds
    ]
    return {
        "schema_version": 1,
        "candidates": candidates,
        "ignored_span_ids": list(span_ids[1:] if candidates else span_ids),
        "warnings": [],
    }


class FakeLlm:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_structured(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(
            parsed=response,
            text=json.dumps(response),
            provider="fake-provider",
            model="fake-model",
            agent_id="aux",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


class ExtractionContractTests(unittest.TestCase):
    def test_private_fixture_requires_safe_basename_regular_file_and_exact_sha(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory)
            private_root = data_path / "eval/private"
            private_root.mkdir(parents=True)
            private_root.chmod(0o700)
            fixture = private_root / "golden-v1.json"
            fixture.write_text(
                json.dumps(
                    {
                        "fixture_version": 1,
                        "dataset": "private-golden",
                        "cases": [
                            {
                                "id": "case-1",
                                "messages": [{"id": "m1", "role": "user", "content": "private"}],
                                "expected_kinds": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            fixture.chmod(0o600)
            digest = sha256(fixture.read_bytes()).hexdigest()

            loaded = load_private_fixture(data_path, "golden-v1.json", digest)
            self.assertEqual(fixture.read_bytes(), loaded.content)
            self.assertEqual(digest, loaded.content_sha256)
            with self.assertRaisesRegex(EvaluationError, "JSON basename"):
                load_private_fixture(data_path, "../golden-v1.json", digest)
            with self.assertRaisesRegex(EvaluationError, "does not match"):
                load_private_fixture(data_path, "golden-v1.json", "0" * 64)

            fixture.chmod(0o644)
            with self.assertRaisesRegex(EvaluationError, "owner-only"):
                load_private_fixture(data_path, "golden-v1.json", digest)
            fixture.chmod(0o600)

            link = private_root / "linked.json"
            link.symlink_to(fixture)
            with self.assertRaisesRegex(EvaluationError, "missing or unsafe"):
                load_private_fixture(data_path, "linked.json", digest)

            fixture.unlink()
            metrics = evaluate_fixture(
                loaded,
                lambda item: ExtractionResult((), item.span_ids, ()),
            )
            self.assertEqual(1, metrics.cases)
            self.assertEqual(digest, loaded.content_sha256)

    def test_fixture_contract_is_fully_validated_before_any_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "invalid.json"
            fixture.write_text(
                json.dumps(
                    {
                        "cases": [
                            {
                                "id": "valid-first-case",
                                "messages": [{"id": "m1", "role": "user", "content": "Valid"}],
                                "expected_kinds": [],
                            },
                            {
                                "id": "invalid-second-case",
                                "messages": [{"id": "m2", "role": "user", "content": "Invalid"}],
                                "expected_kinds": ["unsupported"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            calls = 0

            def extractor(item: ConversationSegment) -> ExtractionResult:
                nonlocal calls
                calls += 1
                return ExtractionResult((), item.span_ids, ())

            with self.assertRaisesRegex(ValueError, "unsupported candidate kind"):
                evaluate_fixture(fixture, extractor)
            self.assertEqual(0, calls)

    def test_candidate_provenance_and_full_span_accounting_are_required(self) -> None:
        result = validate_extraction_payload(valid_payload(), allowed_span_ids=("m1", "m2"))
        self.assertEqual(("m1",), result.candidates[0].source_span_ids)

        outside = valid_payload()
        outside["candidates"][0]["source_span_ids"] = ["unknown"]
        with self.assertRaises(ExtractionError):
            validate_extraction_payload(outside, allowed_span_ids=("m1", "m2"))

        uncovered = valid_payload()
        uncovered["ignored_span_ids"] = []
        with self.assertRaises(ExtractionError):
            validate_extraction_payload(uncovered, allowed_span_ids=("m1", "m2"))

    def test_service_is_tool_free_namespaced_and_keeps_injection_in_data(self) -> None:
        payload = {
            "schema_version": 1,
            "candidates": [],
            "ignored_span_ids": ["m1", "m2"],
            "warnings": ["instruction_like_text"],
        }
        llm = FakeLlm([payload])

        outcome = ExtractionService(llm).extract(segment(injection=True))

        self.assertEqual((), outcome.result.candidates)
        call = llm.calls[0]
        self.assertEqual("nexus_extract", call["task"])
        self.assertNotIn("provider", call)
        self.assertNotIn("model", call)
        self.assertIn("RUN_THIS_SECRET_COMMAND_123", call["input"][0]["text"])
        self.assertNotIn("RUN_THIS_SECRET_COMMAND_123", call["instructions"])
        self.assertEqual("nexus-extraction-prompt-v2", PROMPT_VERSION)
        self.assertIn("Never repeat the same fact under multiple kinds", call["instructions"])
        self.assertIn("correction, commitment, relation, entity, then memory", call["instructions"])
        self.assertEqual(1, outcome.audit.attempts)

    def test_invalid_output_retries_once_then_accepts_valid_payload(self) -> None:
        llm = FakeLlm([{"bad": True}, valid_payload()])

        outcome = ExtractionService(llm, max_attempts=2).extract(segment())

        self.assertEqual(2, len(llm.calls))
        self.assertEqual(2, outcome.audit.attempts)

    def test_provider_errors_have_a_bounded_retry(self) -> None:
        llm = FakeLlm([RuntimeError("secret provider detail"), RuntimeError("again")])

        with self.assertRaisesRegex(ExtractionError, "after 2 bounded attempt") as raised:
            ExtractionService(llm, max_attempts=2).extract(segment())

        self.assertEqual(2, len(llm.calls))
        self.assertNotIn("secret provider detail", str(raised.exception))
        self.assertEqual("provider_or_runtime", raised.exception.failure_class)

    def test_sdk_timeout_errors_map_to_timeout_without_echoing(self) -> None:
        class APITimeoutError(Exception):
            pass

        llm = FakeLlm([APITimeoutError("Request timed out. secret"), APITimeoutError("again")])

        with self.assertRaises(ExtractionError) as raised:
            ExtractionService(llm, max_attempts=2).extract(segment())

        self.assertEqual("timeout", raised.exception.failure_class)
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("Request timed out", str(raised.exception))

    def test_http_status_errors_map_without_echoing_body(self) -> None:
        class FakeHTTPError(Exception):
            def __init__(self, status_code: int, body: str) -> None:
                super().__init__(body)
                self.status_code = status_code

        llm = FakeLlm(
            [FakeHTTPError(404, "model secret-body"), FakeHTTPError(404, "again secret-body")]
        )

        with self.assertRaises(ExtractionError) as raised:
            ExtractionService(llm, max_attempts=2).extract(segment())

        self.assertEqual("http_4xx", raised.exception.failure_class)
        self.assertNotIn("secret-body", str(raised.exception))

    def test_timeout_cause_chain_is_classified_without_source_text(self) -> None:
        class APITimeoutError(Exception):
            pass

        class Wrapper(Exception):
            pass

        inner = APITimeoutError("hidden timeout payload")
        wrapped = Wrapper("wrapper secret")
        wrapped.__cause__ = inner
        llm = FakeLlm([wrapped, wrapped])

        with self.assertRaises(ExtractionError) as raised:
            ExtractionService(llm, max_attempts=2).extract(segment())

        self.assertEqual("timeout", raised.exception.failure_class)
        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("hidden timeout", str(raised.exception))

    def test_provider_timeout_is_cut_locally_without_raising_the_cap(self) -> None:
        import time

        class SlowLlm:
            def complete_structured(self, **kwargs: object) -> object:
                time.sleep(0.6)
                return SimpleNamespace(parsed=valid_payload(), text="{}", usage=None)

        started = time.monotonic()
        with self.assertRaises(ExtractionError) as raised:
            ExtractionService(SlowLlm(), max_attempts=1, timeout_seconds=0.15).extract(segment())
        elapsed = time.monotonic() - started
        self.assertEqual("timeout", raised.exception.failure_class)
        self.assertLess(elapsed, 0.45)
        self.assertEqual(90, __import__("nexus.ingest_v2", fromlist=["V2_HARD_TIMEOUT_SECONDS"]).V2_HARD_TIMEOUT_SECONDS)

    def test_timed_out_provider_thread_blocks_overlapping_calls(self) -> None:
        import threading
        import time

        ExtractionService.reset_in_flight_for_tests()

        class SlowLlm:
            def __init__(self) -> None:
                self.starts = 0
                self.flight = 0
                self.max_flight = 0
                self.lock = threading.Lock()

            def complete_structured(self, **kwargs: object) -> object:
                with self.lock:
                    self.starts += 1
                    self.flight += 1
                    self.max_flight = max(self.max_flight, self.flight)
                try:
                    time.sleep(0.45)
                    return SimpleNamespace(parsed=valid_payload(), text="{}", usage=None)
                finally:
                    with self.lock:
                        self.flight -= 1

        llm = SlowLlm()
        with self.assertRaises(ExtractionError) as raised:
            ExtractionService(llm, max_attempts=1, timeout_seconds=0.12).extract(segment())
        self.assertEqual("timeout", raised.exception.failure_class)
        for _ in range(2):
            with self.assertRaises(ExtractorBusy):
                ExtractionService(llm, max_attempts=1, timeout_seconds=0.12).extract(segment())
        self.assertEqual(1, llm.starts)
        self.assertEqual(1, llm.max_flight)
        deadline = time.monotonic() + 1.0
        while ExtractionService.in_flight_count() and time.monotonic() < deadline:
            time.sleep(0.02)
        ExtractionService.reset_in_flight_for_tests()

    def test_invalid_json_failure_class_does_not_echo_payload(self) -> None:
        class BrokenJsonLlm:
            def complete_structured(self, **kwargs):
                return SimpleNamespace(parsed=None, text="not-json {", usage=None)

        with self.assertRaises(ExtractionError) as raised:
            ExtractionService(BrokenJsonLlm(), max_attempts=2).extract(segment())

        self.assertEqual("invalid_json", raised.exception.failure_class)
        self.assertNotIn("not-json", str(raised.exception))

    def test_frozen_contract_holdout_records_expected_metrics(self) -> None:
        fixture = frozen_fixture_path()
        fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
        expected_by_case = {
            item["id"]: item["expected_kinds"] for item in fixture_payload["cases"]
        }

        def fake_extract(item: ConversationSegment) -> ExtractionResult:
            kinds = expected_by_case[item.conversation_id]
            candidates = tuple(
                ExtractionCandidate(
                    kind=CandidateKind(kind),
                    statement=f"Synthetic expected {kind}",
                    entity_mentions=(),
                    temporal_expression=None,
                    source_span_ids=(item.span_ids[0],),
                    confidence=0.95,
                    ambiguity_flags=(),
                    possible_supersedes=(),
                )
                for kind in kinds
            )
            ignored = item.span_ids[1:] if candidates else item.span_ids
            return ExtractionResult(candidates, ignored, ())

        metrics = evaluate_fixture(fixture, fake_extract)
        baseline = json.loads(
            (ROOT / "eval" / "baseline-phase3-contract.json").read_text(encoding="utf-8")
        )

        self.assertEqual(baseline["metrics"], metrics.to_dict())
        self.assertEqual(1.0, metrics.provenance_rate)
        self.assertEqual(1.0, metrics.expected_kind_precision)
        self.assertEqual(1.0, metrics.exact_case_match_rate)
        self.assertEqual(0, metrics.schema_failures)

    def test_eval_precision_penalizes_unexpected_candidates(self) -> None:
        def over_extract(item: ConversationSegment) -> ExtractionResult:
            candidate = ExtractionCandidate(
                kind=CandidateKind.MEMORY,
                statement="Unsupported synthetic memory",
                entity_mentions=(),
                temporal_expression=None,
                source_span_ids=(item.span_ids[0],),
                confidence=0.95,
                ambiguity_flags=(),
                possible_supersedes=(),
            )
            return ExtractionResult((candidate,), item.span_ids[1:], ())

        metrics = evaluate_fixture(frozen_fixture_path(), over_extract)

        self.assertLess(metrics.expected_kind_precision, 0.90)
        self.assertLess(metrics.exact_case_match_rate, 0.80)
        self.assertEqual(0.0, metrics.empty_case_precision)

    def test_live_report_contains_audit_metadata_but_no_candidate_content(self) -> None:
        fixture = frozen_fixture_path()
        fixture_payload = json.loads(fixture.read_text(encoding="utf-8"))
        responses = [
            expected_payload(
                tuple(message["id"] for message in item["messages"]),
                item["expected_kinds"],
            )
            for item in fixture_payload["cases"]
        ]

        report = evaluate_with_llm_report(fixture, FakeLlm(responses))
        payload = report.to_dict()

        self.assertTrue(report.accepted)
        self.assertEqual(("fake-provider",), report.providers)
        self.assertEqual(("fake-model",), report.models)
        self.assertEqual(12, report.successful_calls)
        self.assertEqual(180, report.total_tokens)
        self.assertNotIn("candidates", payload)
        self.assertNotIn("Kullanıcı kısa", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
