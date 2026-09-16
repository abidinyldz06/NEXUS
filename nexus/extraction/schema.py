"""Extraction JSON Schema v1 and strict local validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..errors import ExtractionError


EXTRACTION_SCHEMA_VERSION = 1


class CandidateKind(StrEnum):
    MEMORY = "memory"
    ENTITY = "entity"
    RELATION = "relation"
    COMMITMENT = "commitment"
    CORRECTION = "correction"


EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "candidates", "ignored_span_ids", "warnings"],
    "properties": {
        "schema_version": {"const": EXTRACTION_SCHEMA_VERSION},
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "kind",
                    "statement",
                    "entity_mentions",
                    "temporal_expression",
                    "source_span_ids",
                    "confidence",
                    "ambiguity_flags",
                    "possible_supersedes",
                ],
                "properties": {
                    "kind": {"enum": [item.value for item in CandidateKind]},
                    "statement": {"type": "string", "minLength": 1},
                    "entity_mentions": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "temporal_expression": {"type": ["string", "null"]},
                    "source_span_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "ambiguity_flags": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "possible_supersedes": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
        "ignored_span_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "warnings": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}


def _string_tuple(value: Any, field_name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ExtractionError(f"{field_name} must be an array of non-empty strings")
    if nonempty and not value:
        raise ExtractionError(f"{field_name} must not be empty")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ExtractionCandidate:
    kind: CandidateKind
    statement: str
    entity_mentions: tuple[str, ...]
    temporal_expression: str | None
    source_span_ids: tuple[str, ...]
    confidence: float
    ambiguity_flags: tuple[str, ...]
    possible_supersedes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    candidates: tuple[ExtractionCandidate, ...]
    ignored_span_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: int = EXTRACTION_SCHEMA_VERSION


def validate_extraction_payload(
    payload: Any, *, allowed_span_ids: tuple[str, ...]
) -> ExtractionResult:
    if not isinstance(payload, dict):
        raise ExtractionError("extraction result must be a JSON object")
    if set(payload) != {"schema_version", "candidates", "ignored_span_ids", "warnings"}:
        raise ExtractionError("extraction result has missing or unknown fields")
    if payload["schema_version"] != EXTRACTION_SCHEMA_VERSION:
        raise ExtractionError("unsupported extraction schema version")
    raw_candidates = payload["candidates"]
    if not isinstance(raw_candidates, list):
        raise ExtractionError("candidates must be an array")
    allowed = set(allowed_span_ids)
    candidates: list[ExtractionCandidate] = []
    cited: set[str] = set()
    required_fields = {
        "kind",
        "statement",
        "entity_mentions",
        "temporal_expression",
        "source_span_ids",
        "confidence",
        "ambiguity_flags",
        "possible_supersedes",
    }
    for raw in raw_candidates:
        if not isinstance(raw, dict) or set(raw) != required_fields:
            raise ExtractionError("candidate has missing or unknown fields")
        try:
            kind = CandidateKind(raw["kind"])
        except (TypeError, ValueError) as exc:
            raise ExtractionError("candidate kind is invalid") from exc
        statement = raw["statement"]
        if not isinstance(statement, str) or not statement.strip():
            raise ExtractionError("candidate statement must not be empty")
        confidence = raw["confidence"]
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
        ):
            raise ExtractionError("candidate confidence must be between 0 and 1")
        spans = _string_tuple(raw["source_span_ids"], "source_span_ids", nonempty=True)
        if not set(spans) <= allowed:
            raise ExtractionError("candidate cites a span outside the input segment")
        temporal = raw["temporal_expression"]
        if temporal is not None and not isinstance(temporal, str):
            raise ExtractionError("temporal_expression must be a string or null")
        candidates.append(
            ExtractionCandidate(
                kind=kind,
                statement=statement.strip(),
                entity_mentions=_string_tuple(raw["entity_mentions"], "entity_mentions"),
                temporal_expression=temporal,
                source_span_ids=spans,
                confidence=float(confidence),
                ambiguity_flags=_string_tuple(raw["ambiguity_flags"], "ambiguity_flags"),
                possible_supersedes=_string_tuple(
                    raw["possible_supersedes"], "possible_supersedes"
                ),
            )
        )
        cited.update(spans)

    ignored = _string_tuple(payload["ignored_span_ids"], "ignored_span_ids")
    if not set(ignored) <= allowed:
        raise ExtractionError("ignored_span_ids contains a span outside the input segment")
    if cited & set(ignored):
        raise ExtractionError("a span cannot be both cited and ignored")
    if cited | set(ignored) != allowed:
        raise ExtractionError("every input span must be cited or explicitly ignored")
    return ExtractionResult(
        candidates=tuple(candidates),
        ignored_span_ids=ignored,
        warnings=_string_tuple(payload["warnings"], "warnings"),
    )
