"""Deterministic Phase 4 policy decisions; no publication side effects."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from .contracts import DuePrecision, Impact, MemoryType
from .entity import EntityResolution, ResolutionStatus
from .extraction.schema import CandidateKind


class PolicyAction(StrEnum):
    WOULD_PUBLISH = "would_publish"
    REVIEW = "review"
    DISCARD = "discard"
    QUARANTINE = "quarantine"


class Sensitivity(StrEnum):
    NONE = "none"
    FINANCIAL = "financial"
    HEALTH = "health"
    LEGAL_IDENTITY = "legal_identity"
    CREDENTIAL = "credential"
    EXTERNAL_ACTION = "external_action"


_SENSITIVITY_TERMS: dict[Sensitivity, tuple[str, ...]] = {
    Sensitivity.FINANCIAL: (
        "borç",
        "ödeme",
        "bütçe",
        "kredi kartı",
        "bank account",
        "debt",
        "payment",
        "budget",
    ),
    Sensitivity.HEALTH: (
        "tanı",
        "ilaç",
        "reçete",
        "sağlık",
        "diagnosis",
        "medication",
        "prescription",
        "health",
    ),
    Sensitivity.LEGAL_IDENTITY: (
        "pasaport",
        "kimlik numarası",
        "dava",
        "sözleşme",
        "passport",
        "identity number",
        "lawsuit",
        "legal contract",
    ),
    Sensitivity.CREDENTIAL: (
        "parola",
        "şifre",
        "api key",
        "private key",
        "mfa",
        "totp",
        "password",
        "credential",
    ),
    Sensitivity.EXTERNAL_ACTION: (
        "mesaj gönder",
        "telefon et",
        "satın al",
        "send a message",
        "make a call",
        "purchase",
    ),
}

_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|gho|github_pat)_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    re.compile(r"\bxoxb-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\b(?:password|parola|şifre|token|api[_ -]?key)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(
        r"\b[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|API_KEY|ACCESS_KEY)[A-Z0-9_]*\s*=\s*\S+"
    ),
)

_STATEMENT_HEX_SECRET = re.compile(r"\b[0-9a-fA-F]{40,}\b")

_HIGH_ENTROPY_TOKEN = re.compile(r"\b[A-Za-z0-9_\-+/=]{24,}\b")
_AUTO_ACCEPT_MIN = 0.7
_REJECT_MAX = 0.4


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _high_entropy_secret(text: str) -> bool:
    for match in _HIGH_ENTROPY_TOKEN.finditer(text):
        token = match.group(0)
        if _shannon_entropy(token) >= 4.0:
            return True
    return False


def redact_secrets(text: str) -> str:
    """Replace secret-shaped substrings. Derived stores must not keep them."""
    redacted = text
    for pattern in _SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def classify_sensitivity(statement: str) -> Sensitivity:
    folded = statement.casefold()
    for sensitivity, terms in _SENSITIVITY_TERMS.items():
        if any(term in folded for term in terms):
            return sensitivity
    return Sensitivity.NONE


def contains_secret_value(statement: str) -> bool:
    if any(pattern.search(statement) is not None for pattern in _SECRET_VALUE_PATTERNS):
        return True
    if _STATEMENT_HEX_SECRET.search(statement) is not None:
        return True
    return _high_entropy_secret(statement)


def ingest_write_disposition(statement: str, confidence: float) -> str:
    """Pilot write gate. Finance/health never auto-write."""
    sensitivity = classify_sensitivity(statement)
    if contains_secret_value(statement):
        return "reject"
    if sensitivity in {Sensitivity.FINANCIAL, Sensitivity.HEALTH}:
        return "review"
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
        or confidence < _REJECT_MAX
    ):
        return "reject"
    if confidence < _AUTO_ACCEPT_MIN:
        return "review"
    return "accept"


@dataclass(frozen=True, slots=True)
class PolicyInput:
    kind: CandidateKind
    statement: str
    confidence: float
    source_span_ids: tuple[str, ...]
    impact: Impact = Impact.LOW
    memory_type: MemoryType | None = None
    due_precision: DuePrecision | None = None
    ambiguity_flags: tuple[str, ...] = ()
    entity_resolutions: tuple[EntityResolution, ...] = ()
    user_asserted: bool = True
    contains_tool_instruction: bool = False


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: PolicyAction
    impact: Impact
    sensitivity: Sensitivity
    reason_codes: tuple[str, ...]


def evaluate_policy(candidate: PolicyInput) -> PolicyDecision:
    """Return a pure decision; Phase 4 never writes a canonical record."""
    sensitivity = classify_sensitivity(candidate.statement)
    reasons: list[str] = []

    if (
        isinstance(candidate.confidence, bool)
        or not isinstance(candidate.confidence, (int, float))
        or not 0 <= candidate.confidence <= 1
    ):
        return PolicyDecision(
            PolicyAction.QUARANTINE,
            Impact.HIGH,
            sensitivity,
            ("invalid_confidence",),
        )
    if not candidate.statement.strip():
        return PolicyDecision(
            PolicyAction.QUARANTINE,
            Impact.HIGH,
            sensitivity,
            ("empty_statement",),
        )
    if not candidate.source_span_ids:
        return PolicyDecision(
            PolicyAction.QUARANTINE,
            Impact.HIGH,
            sensitivity,
            ("missing_provenance",),
        )
    if contains_secret_value(candidate.statement):
        return PolicyDecision(
            PolicyAction.QUARANTINE,
            Impact.HIGH,
            Sensitivity.CREDENTIAL,
            ("secret_like_value",),
        )
    if candidate.contains_tool_instruction:
        return PolicyDecision(
            PolicyAction.QUARANTINE,
            Impact.HIGH,
            sensitivity,
            ("tool_instruction",),
        )
    if not candidate.user_asserted:
        return PolicyDecision(
            PolicyAction.DISCARD,
            candidate.impact,
            sensitivity,
            ("assistant_speculation",),
        )

    impact = Impact.HIGH if sensitivity is not Sensitivity.NONE else candidate.impact
    entity_ambiguous = any(
        resolution.status
        in {ResolutionStatus.AMBIGUOUS, ResolutionStatus.INVALID_REFERENCE}
        for resolution in candidate.entity_resolutions
    )
    if candidate.ambiguity_flags:
        reasons.append("candidate_ambiguous")
    if entity_ambiguous:
        reasons.append("entity_ambiguous")
    if candidate.kind is CandidateKind.CORRECTION:
        impact = Impact.HIGH
        reasons.append("destructive_correction")
    if sensitivity is not Sensitivity.NONE:
        reasons.append(f"sensitive_{sensitivity.value}")
    if impact is Impact.HIGH:
        reasons.append("high_impact")
    if reasons:
        return PolicyDecision(
            PolicyAction.REVIEW,
            impact,
            sensitivity,
            tuple(dict.fromkeys(reasons)),
        )

    if candidate.confidence < 0.75:
        return PolicyDecision(
            PolicyAction.REVIEW,
            impact,
            sensitivity,
            ("low_confidence_with_evidence",),
        )
    if candidate.confidence < 0.90:
        return PolicyDecision(
            PolicyAction.REVIEW,
            impact,
            sensitivity,
            ("medium_confidence",),
        )

    allowlisted = (
        impact is Impact.LOW
        and (
            candidate.kind is CandidateKind.MEMORY
            and candidate.memory_type in {MemoryType.EVENT, MemoryType.PREFERENCE}
            or candidate.kind is CandidateKind.COMMITMENT
            and candidate.due_precision in {DuePrecision.EXACT, DuePrecision.DAY}
        )
    )
    if allowlisted:
        return PolicyDecision(
            PolicyAction.WOULD_PUBLISH,
            impact,
            sensitivity,
            ("shadow_allowlist",),
        )
    return PolicyDecision(
        PolicyAction.REVIEW,
        impact,
        sensitivity,
        ("type_not_auto_publish_allowlisted",),
    )
