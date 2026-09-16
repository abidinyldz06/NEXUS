"""Deterministic evaluation runner for extraction fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path

from ..extraction.schema import ExtractionResult
from ..normalize import NormalizedConversation, NormalizedMessage, conversation_bounds
from ..segmenter import ConversationSegment, segment_conversation


@dataclass(frozen=True, slots=True)
class EvalMetrics:
    cases: int
    segments: int
    candidates: int
    provenance_rate: float
    expected_kind_recall: float
    empty_case_precision: float
    schema_failures: int

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ShadowEvalReport:
    metrics: EvalMetrics
    fixture_sha256: str
    providers: tuple[str, ...]
    models: tuple[str, ...]
    agent_ids: tuple[str, ...]
    prompt_version: str
    prompt_sha256: str
    schema_version: int
    successful_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int

    @property
    def accepted(self) -> bool:
        return (
            self.metrics.provenance_rate == 1.0
            and self.metrics.expected_kind_recall >= 0.80
            and self.metrics.empty_case_precision == 1.0
            and self.metrics.schema_failures == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "metrics": self.metrics.to_dict(),
            "fixture_sha256": self.fixture_sha256,
            "providers": list(self.providers),
            "models": list(self.models),
            "agent_ids": list(self.agent_ids),
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
            "schema_version": self.schema_version,
            "successful_calls": self.successful_calls,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            },
        }


def frozen_fixture_path() -> Path:
    return Path(str(files("nexus.eval").joinpath("fixtures/extraction_holdout_v1.json")))


def _conversation(raw: dict[str, object]) -> NormalizedConversation:
    case_id = str(raw["id"])
    raw_messages = raw.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError(f"eval case {case_id} has no messages")
    messages = tuple(
        NormalizedMessage.build(
            message_id=str(message["id"]),
            role=message["role"],
            content=message["content"],
            created_at=message.get("created_at"),
            source_locator=f"eval:{case_id}#message={message['id']}",
        )
        for message in raw_messages
        if isinstance(message, dict)
    )
    started_at, ended_at = conversation_bounds(messages)
    return NormalizedConversation(
        external_conversation_id=case_id,
        title=f"Frozen eval case {case_id}",
        participants=tuple(sorted({message.role for message in messages})),
        messages=messages,
        source_locator=f"eval:{case_id}",
        started_at=started_at,
        ended_at=ended_at,
    )


def evaluate_fixture(
    path: Path,
    extractor: Callable[[ConversationSegment], ExtractionResult],
    *,
    max_segment_chars: int = 12_000,
) -> EvalMetrics:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("eval fixture must contain a non-empty cases array")

    segment_count = 0
    candidate_count = 0
    candidates_with_provenance = 0
    expected_total = 0
    expected_matched = 0
    empty_cases = 0
    empty_cases_correct = 0
    schema_failures = 0

    for raw_case in cases:
        if not isinstance(raw_case, dict):
            raise ValueError("eval case must be an object")
        conversation = _conversation(raw_case)
        segments = segment_conversation(conversation, max_chars=max_segment_chars)
        segment_count += len(segments)
        actual_kinds: list[str] = []
        case_candidate_count = 0
        for segment in segments:
            try:
                result = extractor(segment)
            except Exception:
                schema_failures += 1
                continue
            allowed = set(segment.span_ids)
            cited = {
                span_id
                for candidate in result.candidates
                for span_id in candidate.source_span_ids
            }
            ignored = set(result.ignored_span_ids)
            if (
                any(not candidate.source_span_ids for candidate in result.candidates)
                or not cited <= allowed
                or not ignored <= allowed
                or cited & ignored
                or cited | ignored != allowed
            ):
                schema_failures += 1
                continue
            candidate_count += len(result.candidates)
            case_candidate_count += len(result.candidates)
            for candidate in result.candidates:
                actual_kinds.append(candidate.kind.value)
                if candidate.source_span_ids:
                    candidates_with_provenance += 1
        expected = raw_case.get("expected_kinds", [])
        if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
            raise ValueError("expected_kinds must be an array of strings")
        expected_total += len(expected)
        remaining = list(actual_kinds)
        for kind in expected:
            if kind in remaining:
                expected_matched += 1
                remaining.remove(kind)
        if not expected:
            empty_cases += 1
            if case_candidate_count == 0:
                empty_cases_correct += 1

    return EvalMetrics(
        cases=len(cases),
        segments=segment_count,
        candidates=candidate_count,
        provenance_rate=(candidates_with_provenance / candidate_count if candidate_count else 1.0),
        expected_kind_recall=(expected_matched / expected_total if expected_total else 1.0),
        empty_case_precision=(empty_cases_correct / empty_cases if empty_cases else 1.0),
        schema_failures=schema_failures,
    )


def evaluate_with_llm(
    path: Path,
    llm: object,
    *,
    max_segment_chars: int = 12_000,
    max_attempts: int = 2,
) -> EvalMetrics:
    """Run the frozen fixture through Hermes's plugin-owned LLM route in shadow mode."""
    return evaluate_with_llm_report(
        path,
        llm,
        max_segment_chars=max_segment_chars,
        max_attempts=max_attempts,
    ).metrics


def evaluate_with_llm_report(
    path: Path,
    llm: object,
    *,
    max_segment_chars: int = 12_000,
    max_attempts: int = 2,
) -> ShadowEvalReport:
    """Run a model-quality shadow eval and retain only non-content audit metadata."""
    from ..extraction.service import PROMPT_VERSION, ExtractionService

    service = ExtractionService(llm, max_attempts=max_attempts)
    audits = []

    def extract(segment: ConversationSegment) -> ExtractionResult:
        outcome = service.extract(segment)
        audits.append(outcome.audit)
        return outcome.result

    metrics = evaluate_fixture(
        path,
        extract,
        max_segment_chars=max_segment_chars,
    )
    fixture_digest = sha256(path.read_bytes()).hexdigest()
    return ShadowEvalReport(
        metrics=metrics,
        fixture_sha256=fixture_digest,
        providers=tuple(sorted({audit.provider for audit in audits if audit.provider})),
        models=tuple(sorted({audit.model for audit in audits if audit.model})),
        agent_ids=tuple(sorted({audit.agent_id for audit in audits if audit.agent_id})),
        prompt_version=audits[0].prompt_version if audits else PROMPT_VERSION,
        prompt_sha256=service.prompt_sha256,
        schema_version=audits[0].schema_version if audits else 1,
        successful_calls=len(audits),
        input_tokens=sum(audit.input_tokens for audit in audits),
        output_tokens=sum(audit.output_tokens for audit in audits),
        total_tokens=sum(audit.total_tokens for audit in audits),
    )
