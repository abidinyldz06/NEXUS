"""Deterministic evaluation runner for extraction fixtures."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

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
    from ..extraction.service import ExtractionService

    service = ExtractionService(llm, max_attempts=max_attempts)
    return evaluate_fixture(
        path,
        lambda segment: service.extract(segment).result,
        max_segment_chars=max_segment_chars,
    )
