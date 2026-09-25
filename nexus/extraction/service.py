"""Tool-free Hermes structured extraction service."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from typing import Any

from ..errors import ExtractionError
from ..segmenter import ConversationSegment
from .schema import EXTRACTION_JSON_SCHEMA, ExtractionResult, validate_extraction_payload

PROMPT_VERSION = "nexus-extraction-prompt-v2"


class ExtractorBusy(Exception):
    """The previous provider call still owns the flight. This segment was not sent."""


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return tuple(seen)


def classify_extraction_failure(exc: BaseException) -> str:
    """Map a complete_structured failure to a content-free failure_class.

    Exception messages are never copied into the returned label.
    """
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ExtractionError):
        return "schema_invalid"
    for item in _exception_chain(exc):
        if isinstance(item, TimeoutError):
            return "timeout"
        name = type(item).__name__.lower()
        if "timeout" in name:
            return "timeout"
        status = getattr(item, "status_code", None)
        if status is None:
            status = getattr(item, "status", None)
        if isinstance(status, int) and not isinstance(status, bool):
            if 400 <= status < 500:
                return "http_4xx"
            if 500 <= status < 600:
                return "http_5xx"
    return "provider_or_runtime"


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
    _flight_lock = threading.Lock()
    _in_flight = 0
    _in_flight_cond = threading.Condition(_flight_lock)

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
        package = __package__ or "nexus.extraction"
        self.instructions = (
            files(package).joinpath("prompt_v2.txt").read_text(encoding="utf-8").strip()
        )
        self.prompt_sha256 = sha256(self.instructions.encode("utf-8")).hexdigest()

    @classmethod
    def in_flight_count(cls) -> int:
        with cls._flight_lock:
            return cls._in_flight

    @classmethod
    def reset_in_flight_for_tests(cls) -> None:
        with cls._in_flight_cond:
            cls._in_flight = 0
            cls._in_flight_cond.notify_all()

    def _acquire_flight_until(self, deadline: float) -> float:
        with self._in_flight_cond:
            while ExtractionService._in_flight > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExtractorBusy()
                self._in_flight_cond.wait(timeout=remaining)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExtractorBusy()
            ExtractionService._in_flight += 1
            return remaining

    def _release_flight(self) -> None:
        with self._in_flight_cond:
            ExtractionService._in_flight = max(0, ExtractionService._in_flight - 1)
            self._in_flight_cond.notify_all()

    def _complete_structured(self, **kwargs: Any) -> Any:
        """Wait at most ``timeout`` seconds even if the provider ignores its own cap.

        Queue wait and the provider call share that budget. A timed-out provider
        thread is not cancelled; the next segment waits, and if the budget
        elapses before a new call starts it is not counted as a model attempt.
        """
        timeout = float(kwargs.get("timeout") or self.timeout_seconds)
        deadline = time.monotonic() + timeout
        remaining = self._acquire_flight_until(deadline)
        released = False

        def release() -> None:
            nonlocal released
            if released:
                return
            released = True
            self._release_flight()

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nexus-extract")
        future = None
        try:
            future = pool.submit(self.llm.complete_structured, **kwargs)
            try:
                return future.result(timeout=remaining)
            except FuturesTimeoutError as exc:
                raise TimeoutError() from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            if future is None or future.done():
                release()
            else:

                def reap() -> None:
                    try:
                        future.result()
                    except Exception:
                        pass
                    finally:
                        release()

                threading.Thread(target=reap, name="nexus-extract-reap", daemon=True).start()

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

        last_class = "structured_output"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._complete_structured(
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
            except ExtractorBusy:
                raise
            except json.JSONDecodeError:
                last_class = "invalid_json"
            except ExtractionError:
                last_class = "schema_invalid"
            except Exception as exc:
                last_class = classify_extraction_failure(exc)
            if attempt == self.max_attempts:
                break
        raise ExtractionError(
            f"structured extraction failed after {self.max_attempts} bounded attempt(s)",
            failure_class=last_class,
        )
