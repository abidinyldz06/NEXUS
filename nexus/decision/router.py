"""Shadow-only live-turn routing. Never executes actions or writes state."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ..config import NexusConfig
from ..errors import DecisionError
from ..policy import Sensitivity, classify_sensitivity, contains_secret_value
from .categories import RouteCategory
from .classifier import predict_with_classifier
from .llm import predict_with_llm

MAX_ROUTE_CHARS = 4000

_COMMAND_PHRASES = (
    "yeniden başlat",
    "restart",
    "reboot",
    "shutdown",
    "dosya sil",
    "delete file",
    "rm -rf",
    "satın al",
    "purchase",
    "mesaj gönder",
    "send a message",
    "telefon et",
    "make a call",
)
_CUSTOMER_PHRASES = ("müşteri", "crm")
_REMINDER_PHRASES = ("hatırlat", "remind me")
_CHAT_PHRASES = ("hava çok güzel", "hava güzel", "nasılsın", "teşekkür")
_MEMORY_PHRASES = ("unutma ki", "tercihim")
_TEMPORARY_PHRASES = ("şimdilik", "geçici bilgi")
_TASK_PHRASES = ("yapmam lazım", "görev olarak")


@dataclass(frozen=True, slots=True)
class _LocalHint:
    category: RouteCategory
    confidence: float
    reason_codes: tuple[str, ...]
    high_risk: bool


@dataclass(frozen=True, slots=True)
class DecisionReport:
    category: RouteCategory
    confidence: float
    backend: str
    sensitivity: Sensitivity
    reason_codes: tuple[str, ...]
    text_sha256: str
    external_classifier_invoked: bool
    llm_fallback_invoked: bool
    high_confidence: float
    low_risk_min: float

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "shadow",
            "writes_performed": False,
            "would_execute": False,
            "needs_human_review": True,
            "approval_policy": "always_required_in_phase_a",
            "category": self.category.value,
            "confidence": self.confidence,
            "backend": self.backend,
            "sensitivity": self.sensitivity.value,
            "reason_codes": list(self.reason_codes),
            "text_sha256": self.text_sha256,
            "external_classifier_invoked": self.external_classifier_invoked,
            "llm_fallback_invoked": self.llm_fallback_invoked,
            "candidate_policy": {
                "high_confidence": self.high_confidence,
                "low_risk_min": self.low_risk_min,
                "enforced": False,
            },
        }


def _local_hint(folded: str) -> _LocalHint:
    if any(phrase in folded for phrase in _COMMAND_PHRASES):
        return _LocalHint(RouteCategory.COMMAND, 1.0, ("high_risk_command",), True)
    if any(phrase in folded for phrase in _CUSTOMER_PHRASES):
        return _LocalHint(RouteCategory.CUSTOMER_OR_CRM, 0.7, ("local_customer_term",), False)
    if any(phrase in folded for phrase in _REMINDER_PHRASES):
        return _LocalHint(RouteCategory.REMINDER, 0.7, ("local_reminder_term",), False)
    if any(phrase in folded for phrase in _TASK_PHRASES):
        return _LocalHint(RouteCategory.TASK, 0.6, ("local_task_term",), False)
    if any(phrase in folded for phrase in _MEMORY_PHRASES):
        return _LocalHint(RouteCategory.DURABLE_MEMORY, 0.6, ("local_memory_term",), False)
    if any(phrase in folded for phrase in _TEMPORARY_PHRASES):
        return _LocalHint(
            RouteCategory.TEMPORARY_INFORMATION, 0.6, ("local_temporary_term",), False
        )
    if any(phrase in folded for phrase in _CHAT_PHRASES):
        return _LocalHint(RouteCategory.CHAT, 0.8, ("local_chat_term",), False)
    return _LocalHint(RouteCategory.UNKNOWN, 0.0, ("no_local_match",), False)


def _allow_external(secret: bool, sensitivity: Sensitivity, hint: _LocalHint) -> bool:
    return not secret and sensitivity is Sensitivity.NONE and not hint.high_risk


def route_text(
    text: str,
    config: NexusConfig,
    *,
    llm: Any = None,
    classifier_runner: Any = None,
) -> DecisionReport:
    if not isinstance(text, str) or not text.strip():
        raise DecisionError("route text is required")
    if len(text) > MAX_ROUTE_CHARS:
        raise DecisionError("route text exceeds the 4000 character limit")

    digest = sha256(text.encode("utf-8")).hexdigest()
    secret = contains_secret_value(text)
    sensitivity = Sensitivity.CREDENTIAL if secret else classify_sensitivity(text)
    hint = _local_hint(text.casefold())
    reasons = list(hint.reason_codes)
    if secret:
        reasons.append("secret_like_value")
    elif sensitivity is not Sensitivity.NONE:
        reasons.append(f"sensitive_{sensitivity.value}")

    category = hint.category
    confidence = hint.confidence
    backend = "local_rules"
    classifier_invoked = False
    llm_invoked = False
    allow_external = _allow_external(secret, sensitivity, hint)

    if not allow_external:
        reasons.append("external_classifier_blocked")
    elif config.decision_classifier_enabled:
        kwargs = {}
        if classifier_runner is not None:
            kwargs["runner"] = classifier_runner
        prediction = predict_with_classifier(
            text,
            executable=config.decision_classifier_executable,
            **kwargs,
        )
        classifier_invoked = True
        category = prediction.category
        confidence = prediction.confidence
        backend = "classifier.dev"
        reasons.append("classifier_prediction")
    elif config.decision_llm_fallback_enabled:
        category, confidence = predict_with_llm(text, llm)
        llm_invoked = True
        backend = "hermes_llm"
        reasons.append("llm_fallback")

    if hint.high_risk:
        category = RouteCategory.COMMAND
        confidence = 1.0
        backend = "local_rules"

    return DecisionReport(
        category=category,
        confidence=confidence,
        backend=backend,
        sensitivity=sensitivity,
        reason_codes=tuple(dict.fromkeys(reasons)),
        text_sha256=digest,
        external_classifier_invoked=classifier_invoked,
        llm_fallback_invoked=llm_invoked,
        high_confidence=config.decision_high_confidence,
        low_risk_min=config.decision_low_risk_min,
    )


__all__ = ["DecisionReport", "RouteCategory", "route_text"]
