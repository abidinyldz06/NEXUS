from __future__ import annotations

import unittest
from datetime import UTC, datetime
from hashlib import sha256

from nexus.commitments import is_due, mark_notified, resolve_due, transition
from nexus.contracts import (
    Commitment,
    CommitmentStatus,
    DuePrecision,
    Impact,
    ReviewStatus,
    SourceRef,
)
from nexus.errors import CommitmentError
from nexus.ids import IdPrefix, new_id


def commitment(**overrides: object) -> Commitment:
    span_id = "msg_1"
    values = {
        "id": new_id(IdPrefix.COMMITMENT),
        "summary": "Cuma Hasan Usta'yı ara",
        "actor_entity_id": new_id(IdPrefix.ENTITY),
        "source_refs": (
            SourceRef(
                source_id=new_id(IdPrefix.SOURCE),
                conversation_id="conversation-1",
                span_ids=(span_id,),
                span_sha256=sha256(span_id.encode()).hexdigest(),
            ),
        ),
        "confidence": 0.98,
        "impact": Impact.LOW,
        "review_status": ReviewStatus.APPROVED,
        "timezone": "Europe/Istanbul",
        "due_date": "2026-09-18",
        "due_precision": DuePrecision.DAY,
        "notify": True,
    }
    values.update(overrides)
    return Commitment(**values)


class CommitmentTests(unittest.TestCase):
    def test_monday_friday_example_resolves_to_the_same_week(self) -> None:
        result = resolve_due(
            "Cuma Hasan Usta'yı ara",
            source_at="2026-09-14T10:00:00+03:00",
        )

        self.assertEqual("2026-09-18", result.due_date)
        self.assertIsNone(result.due_time)
        self.assertEqual(DuePrecision.DAY, result.due_precision)
        self.assertTrue(result.schedulable)

    def test_timezone_conversion_uses_the_local_source_day(self) -> None:
        result = resolve_due(
            "Cuma saat 09.30 ara",
            source_at="2026-03-29T21:30:00Z",
            timezone="Europe/Istanbul",
        )

        self.assertEqual("2026-04-03", result.due_date)
        self.assertEqual("09:30:00", result.due_time)
        self.assertEqual(DuePrecision.EXACT, result.due_precision)

    def test_ambiguous_relative_date_is_never_schedulable(self) -> None:
        result = resolve_due(
            "Hasan Usta'yı bir ara ararım",
            source_at="2026-09-14T10:00:00+03:00",
        )

        self.assertFalse(result.schedulable)
        self.assertEqual(DuePrecision.AMBIGUOUS, result.due_precision)
        self.assertEqual("ambiguous_relative_date", result.reason)

    def test_due_and_notified_lifecycle_is_idempotent(self) -> None:
        item = commitment()
        before = datetime(2026, 9, 17, 20, 59, tzinfo=UTC)
        due = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)

        self.assertFalse(is_due(item, now=before))
        self.assertTrue(is_due(item, now=due))
        notified = mark_notified(item, now=due)
        self.assertEqual("2026-09-18T06:00:00Z", notified.notified_at)
        self.assertFalse(is_due(notified, now=due))
        with self.assertRaises(CommitmentError):
            mark_notified(notified, now=due)

    def test_only_open_commitments_can_transition_once(self) -> None:
        done = transition(commitment(), CommitmentStatus.DONE)
        self.assertEqual(CommitmentStatus.DONE, done.status)
        with self.assertRaises(CommitmentError):
            transition(done, CommitmentStatus.CANCELLED)

    def test_pending_review_is_never_due(self) -> None:
        item = commitment(review_status=ReviewStatus.PENDING)
        now = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)

        self.assertFalse(is_due(item, now=now))


if __name__ == "__main__":
    unittest.main()
