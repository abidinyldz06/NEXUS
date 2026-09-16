from __future__ import annotations

import json
import os
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from nexus.contracts import ReviewStatus, SourceRef
from nexus.errors import ReviewStoreError
from nexus.ids import IdPrefix, new_id
from nexus.review import ReviewStore, create_review_item


def source_ref() -> SourceRef:
    return SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id="conversation-1",
        span_ids=("msg_1",),
        span_sha256=sha256(b"msg_1").hexdigest(),
        excerpt="Kullanıcı kısa yanıtları tercih ediyor.",
    )


class ReviewFlowTests(unittest.TestCase):
    def test_create_decisions_replay_and_duplicate_candidate_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory))
            item = create_review_item(
                candidate_kind="memory",
                candidate={"statement": "Kısa yanıt tercihi"},
                reason_codes=("medium_confidence",),
                source_refs=(source_ref(),),
            )

            first = store.enqueue(item)
            duplicate = store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={"statement": "Kısa yanıt tercihi"},
                    reason_codes=("medium_confidence",),
                    source_refs=(source_ref(),),
                )
            )
            approved = store.decide(first.id, action="approve", reason="Kaynak açık")
            replayed = ReviewStore(Path(directory)).get(first.id)

            self.assertEqual(first.id, duplicate.id)
            self.assertEqual(ReviewStatus.APPROVED, approved.status)
            self.assertEqual(approved, replayed)
            self.assertEqual("approve", replayed.decision["action"])
            self.assertEqual(0o600, os.stat(store.path).st_mode & 0o777)

    def test_edited_approval_keeps_before_after_audit_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory))
            item = store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={"statement": "Eski ifade"},
                    reason_codes=("candidate_ambiguous",),
                    source_refs=(source_ref(),),
                )
            )

            edited = store.decide(
                item.id,
                action="edit",
                reason="İfade netleştirildi",
                edited_candidate={"statement": "Yeni ifade"},
            )

            self.assertEqual(ReviewStatus.EDITED, edited.status)
            self.assertEqual("Yeni ifade", edited.candidate["statement"])
            self.assertNotEqual(
                edited.decision["candidate_before_sha256"],
                edited.decision["candidate_after_sha256"],
            )
            events = [json.loads(line) for line in store.path.read_text().splitlines()]
            self.assertEqual(["create", "edit"], [event["action"] for event in events])

    def test_reading_empty_queue_does_not_create_private_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory) / "missing")

            self.assertEqual((), store.list())
            self.assertFalse(store.directory.exists())

    def test_candidate_kind_is_part_of_the_deduplication_fingerprint(self) -> None:
        memory = create_review_item(
            candidate_kind="memory",
            candidate={"statement": "Aynı ifade"},
            reason_codes=("medium_confidence",),
            source_refs=(source_ref(),),
        )
        entity = create_review_item(
            candidate_kind="entity",
            candidate={"statement": "Aynı ifade"},
            reason_codes=("medium_confidence",),
            source_refs=(source_ref(),),
        )

        self.assertNotEqual(memory.candidate_fingerprint, entity.candidate_fingerprint)

    def test_edit_cannot_change_candidate_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ReviewStore(Path(directory))
            item = store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={"statement": "Eski"},
                    reason_codes=("candidate_ambiguous",),
                    source_refs=(source_ref(),),
                )
            )

            with self.assertRaises(ReviewStoreError):
                store.decide(
                    item.id,
                    action="edit",
                    edited_candidate={"statement": "Yeni", "unknown": True},
                )


if __name__ == "__main__":
    unittest.main()
