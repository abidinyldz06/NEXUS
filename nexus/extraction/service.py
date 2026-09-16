"""Tool-free Hermes structured extraction service."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from typing import Any

from ..errors import ExtractionError
from ..segmenter import ConversationSegment
from .schema import EXTRACTION_JSON_SCHEMA, ExtractionResult, validate_extraction_payload


PROMPT_VERSION = "nexus-extraction-prompt-v1"


@dataclass(frozen=True, slots=True)
class ExtractionAudit:
    provider: str
    model: str
    agent_id: str
    task: str
    prompt_version: str
    prompt_sha256: str
    schema_version: int
    segment_fingerprint: str
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    result: ExtractionResult
    audit: ExtractionAudit


class ExtractionService:
    def __init__(
        self,
        llm: Any,
        *,
        max_attempts: int = 2,
        timeout_seconds: float = 60,
        max_tokens: int = 3000,
    ) -> None:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if timeout_seconds <= 0 or max_tokens <= 0:
            raise ValueError("timeout_seconds and max_tokens must be positive")
        self.llm = llm
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.instructions = (
            files("nexus.extraction")
            .joinpath("prompt_v1.txt")
            .read_text(encoding="utf-8")
            .strip()
        )
        self.prompt_sha256 = sha256(self.instructions.encode("utf-8")).hexdigest()

    def extract(self, segment: ConversationSegment) -> ExtractionOutcome:
        if not segment.messages:
            raise ExtractionError("cannot extract an empty segment")
        data_envelope = {
            "conversation_id": segment.conversation_id,
            "segment_index": segment.index,
            "spans": [
                {
                    "span_id": message.message_id,
                    "role": message.role,
                    "created_at": message.created_at,
                    "content": message.content_text,
                }
                for message in segment.messages
            ],
        }
        input_text = "UNTRUSTED_DATA_JSON\n" + json.dumps(
            data_envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.llm.complete_structured(
                    instructions=self.instructions,
                    input=[{"type": "text", "text": input_text}],
                    json_schema=EXTRACTION_JSON_SCHEMA,
                    schema_name="nexus_extraction_v1",
                    temperature=0,
                    max_tokens=self.max_tokens,
                    timeout=self.timeout_seconds,
                    purpose="NEXUS shadow memory candidate extraction",
                    task="nexus_extract",
                )
                payload = getattr(response, "parsed", None)
                if payload is None:
                    text = getattr(response, "text", "")
                    payload = json.loads(text)
                result = validate_extraction_payload(payload, allowed_span_ids=segment.span_ids)
                usage = getattr(response, "usage", None)
                return ExtractionOutcome(
                    result=result,
                    audit=ExtractionAudit(
                        provider=str(getattr(response, "provider", "")),
                        model=str(getattr(response, "model", "")),
                        agent_id=str(getattr(response, "agent_id", "")),
                        task="nexus_extract",
                        prompt_version=PROMPT_VERSION,
                        prompt_sha256=self.prompt_sha256,
                        schema_version=result.schema_version,
                        segment_fingerprint=segment.fingerprint,
                        attempts=attempt,
                        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                        total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
                    ),
                )
            except Exception:
                if attempt == self.max_attempts:
                    break
        raise ExtractionError(
            f"structured extraction failed after {self.max_attempts} bounded attempt(s)"
        )
