"""Shadow-route observability: privacy-safe JSONL logging, fail-open.

Adds spec items 5+8 without changing route decisions. The logger never
stores source text — only a length-bucket preview policy (default OFF,
opt-in via ``decision_log_preview=True``). Circuit breaker: after N
consecutive classifier failures the hook degrades to local-rules only for
a cooldown window, so user turns never wait on a broken external service
(spec item 8, fail-open).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TextIO

_MAX_PREVIEW_CHARS = 48
_DEFAULT_MAX_BYTES = 512 * 1024
_DEFAULT_COOLDOWN_S = 300.0
_DEFAULT_FAILURE_LIMIT = 3

_MAX_BYTES = max(
    1024,
    int(os.environ.get("NEXUS_CLASSIFIER_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES)),
)


def _privacy_preview(text: str) -> str:
    """Spec 5: raw_text OR a privacy-safe preview. We log a capped preview
    only when the operator opted in; text is never logged by default."""
    if not text:
        return ""
    collapsed = " ".join(str(text).split())
    return collapsed[:_MAX_PREVIEW_CHARS]


@dataclass(frozen=True, slots=True)
class RouteLogEntry:
    """One shadow-route observation. raw_text is never persisted."""

    ts: str
    intent: str
    confidence: float
    latency_ms: int
    success: bool
    backend: str
    classifier_invoked: bool
    llm_fallback_invoked: bool
    needs_human_review: bool
    review_band: str
    reason_codes: tuple[str, ...]
    text_len: int
    preview: str  # privacy-safe preview; empty unless opted in

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.ts,
            "intent": self.intent,
            "confidence": round(float(self.confidence), 4),
            "latency_ms": self.latency_ms,
            "success": self.success,
            "backend": self.backend,
            "classifier_invoked": self.classifier_invoked,
            "llm_fallback_invoked": self.llm_fallback_invoked,
            "needs_human_review": self.needs_human_review,
            "review_band": self.review_band,
            "reason_codes": list(self.reason_codes),
            "text_length": self.text_len,
            "preview": self.preview,
        }


class CircuitBreaker:
    """Fail-open accelerator for the external classifier.

    After ``failure_limit`` consecutive failures the external backend is
    skipped for ``cooldown_seconds``; ``allow_external()`` then returns
    False so ``route_text`` degrades to local-rules (still shadow, never
    a behavior change for the user).
    """

    __slots__ = ("_failure_limit", "_cooldown_s", "_clock", "_failures", "_open_until")

    def __init__(
        self,
        *,
        failure_limit: int = _DEFAULT_FAILURE_LIMIT,
        cooldown_seconds: float = _DEFAULT_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_limit = max(1, failure_limit)
        self._cooldown_s = float(cooldown_seconds)
        self._clock = clock
        self._failures = 0
        self._open_until = 0.0

    def allow_external(self) -> bool:
        if self._clock() < self._open_until:
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._failure_limit:
            self._open_until = self._clock() + self._cooldown_s
            self._failures = 0  # restart the ladder after tripping

    @property
    def is_open(self) -> bool:
        return self._clock() < self._open_until


def _rotate_needed(path: Path) -> bool:
    try:
        return path.stat().st_size >= _MAX_BYTES
    except OSError:
        return False


def append_jsonl(path: Path, entry: RouteLogEntry) -> bool:
    """Append one JSONL row, best-effort. Never raises (spec: fail-open).

    Rotation: one ``.1`` sibling is kept; rows are hard-capped per file by
    rotation so the log cannot grow unbounded on a long-running machine.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if _rotate_needed(path):
            rotated = path.with_name(path.name + ".1")
            try:
                os.replace(path, rotated)
            except OSError:
                pass  # best-effort; keep appending if rotation fails
        line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return True
    except Exception:
        return False


def log_route_report(
    path: Path,
    report: Any,
    *,
    latency_ms: int,
    success: bool,
    text: str = "",
    preview_enabled: bool = False,
    now: str = "",
) -> bool:
    """Build the entry from a DecisionReport and append it. Never raises.

    ``report=None`` (route raised) still writes a failure row — spec 5 wants
    success/failure per message, so a crash is an observation, not silence.
    """
    try:
        if report is None:
            entry = RouteLogEntry(
                ts=now,
                intent="unknown",
                confidence=0.0,
                latency_ms=int(latency_ms),
                success=False,
                backend="error",
                classifier_invoked=False,
                llm_fallback_invoked=False,
                needs_human_review=True,
                review_band="route_error",
                reason_codes=("route_error",),
                text_len=len(text or ""),
                preview=_privacy_preview(text) if preview_enabled else "",
            )
        else:
            entry = RouteLogEntry(
                ts=now,
                intent=getattr(report, "category").value,
                confidence=float(getattr(report, "confidence", 0.0)),
                latency_ms=int(latency_ms),
                success=bool(success),
                backend=str(getattr(report, "backend", "")),
                classifier_invoked=bool(getattr(report, "external_classifier_invoked", False)),
                llm_fallback_invoked=bool(getattr(report, "llm_fallback_invoked", False)),
                needs_human_review=bool(getattr(report, "needs_human_review", False)),
                review_band=str(getattr(report, "review_band", "")),
                reason_codes=tuple(getattr(report, "reason_codes", ()) or ()),
                text_len=len(text or ""),
                preview=_privacy_preview(text) if preview_enabled else "",
            )
        if not entry.ts:
            entry = RouteLogEntry(
                ts=datetime.now().astimezone().isoformat(timespec="seconds"),
                intent=entry.intent,
                confidence=entry.confidence,
                latency_ms=entry.latency_ms,
                success=entry.success,
                backend=entry.backend,
                classifier_invoked=entry.classifier_invoked,
                llm_fallback_invoked=entry.llm_fallback_invoked,
                needs_human_review=entry.needs_human_review,
                review_band=entry.review_band,
                reason_codes=entry.reason_codes,
                text_len=entry.text_len,
                preview=entry.preview,
            )
        return append_jsonl(path, entry)
    except Exception:
        return False


__all__ = [
    "CircuitBreaker",
    "RouteLogEntry",
    "append_jsonl",
    "log_route_report",
]