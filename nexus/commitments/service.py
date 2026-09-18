"""Commitment reconstruction, lifecycle transitions and due evaluation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from ..contracts import (
    Commitment,
    CommitmentStatus,
    DuePrecision,
    Impact,
    ReviewStatus,
    SourceRef,
)
from ..errors import CommitmentError, ContractError


def commitment_from_payload(payload: dict[str, Any]) -> Commitment:
    """Reconstruct and validate a canonical commitment payload."""
    try:
        source_refs = tuple(
            SourceRef(
                source_id=value["source_id"],
                conversation_id=value["conversation_id"],
                span_ids=tuple(value["span_ids"]),
                span_sha256=value["span_sha256"],
                excerpt=value.get("excerpt", ""),
            )
            for value in payload["source_refs"]
        )
        return Commitment(
            id=payload["id"],
            summary=payload["summary"],
            actor_entity_id=payload["actor_entity_id"],
            source_refs=source_refs,
            confidence=payload["confidence"],
            impact=Impact(payload["impact"]),
            review_status=ReviewStatus(payload["review_status"]),
            timezone=payload["timezone"],
            due_date=payload.get("due_date"),
            due_time=payload.get("due_time"),
            due_precision=DuePrecision(payload.get("due_precision", "ambiguous")),
            target_entity_ids=tuple(payload.get("target_entity_ids", ())),
            status=CommitmentStatus(payload.get("status", "open")),
            notify=payload.get("notify", False),
            notified_at=payload.get("notified_at"),
            extractor=dict(payload.get("extractor", {})),
            schema_version=payload.get("schema_version", 1),
        )
    except (KeyError, TypeError, ValueError, ContractError) as exc:
        raise CommitmentError("canonical commitment payload is invalid") from exc


def _local_due_instant(commitment: Commitment) -> datetime | None:
    if commitment.due_date is None:
        return None
    due_date = date.fromisoformat(commitment.due_date)
    due_time = time.fromisoformat(commitment.due_time) if commitment.due_time else time.min
    return datetime.combine(due_date, due_time, tzinfo=ZoneInfo(commitment.timezone))


def is_due(commitment: Commitment, *, now: datetime) -> bool:
    if now.tzinfo is None:
        raise CommitmentError("now must include a timezone offset")
    if (
        commitment.status is not CommitmentStatus.OPEN
        or commitment.review_status
        not in {ReviewStatus.APPROVED, ReviewStatus.EDITED, ReviewStatus.AUTO}
        or not commitment.notify
        or commitment.notified_at is not None
        or commitment.due_precision is DuePrecision.AMBIGUOUS
    ):
        return False
    due = _local_due_instant(commitment)
    return due is not None and now.astimezone(due.tzinfo) >= due


def mark_notified(commitment: Commitment, *, now: datetime) -> Commitment:
    if not is_due(commitment, now=now):
        raise CommitmentError("commitment is not eligible for notification")
    notified_at = now.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return replace(commitment, notified_at=notified_at)


def transition(commitment: Commitment, status: CommitmentStatus) -> Commitment:
    """Apply a conservative terminal lifecycle transition."""
    if commitment.status is not CommitmentStatus.OPEN:
        raise CommitmentError("only open commitments can transition")
    if status not in {
        CommitmentStatus.DONE,
        CommitmentStatus.CANCELLED,
        CommitmentStatus.OVERDUE,
    }:
        raise CommitmentError("target status must be done, cancelled or overdue")
    return replace(commitment, status=status)
