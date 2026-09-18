from __future__ import annotations

import hashlib
import unittest

from nexus.contracts import (
    Commitment,
    DuePrecision,
    Entity,
    EntityType,
    Impact,
    Memory,
    MemoryType,
    ReviewStatus,
    Source,
    SourceRef,
    SourceType,
)
from nexus.errors import ContractError
from nexus.ids import IdPrefix, new_id
from nexus.serialization import dumps


def source_ref() -> SourceRef:
    return SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id="conversation-1",
        span_ids=("msg-1", "msg-2"),
        span_sha256=hashlib.sha256(b"evidence").hexdigest(),
        excerpt="Evidence",
    )


class ContractTests(unittest.TestCase):
    def test_memory_requires_provenance(self) -> None:
        with self.assertRaises(ContractError):
            Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.FACT,
                summary="A fact",
                source_refs=(),
                confidence=0.95,
                impact=Impact.LOW,
                review_status=ReviewStatus.AUTO,
            )

    def test_ambiguous_commitment_cannot_notify(self) -> None:
        with self.assertRaises(ContractError):
            Commitment(
                id=new_id(IdPrefix.COMMITMENT),
                summary="Call Hasan",
                actor_entity_id=new_id(IdPrefix.ENTITY),
                source_refs=(source_ref(),),
                confidence=0.95,
                impact=Impact.MEDIUM,
                review_status=ReviewStatus.AUTO,
                timezone="Europe/Istanbul",
                due_precision=DuePrecision.AMBIGUOUS,
                notify=True,
            )

    def test_commitment_notification_fields_are_strict(self) -> None:
        common = {
            "id": new_id(IdPrefix.COMMITMENT),
            "summary": "Call Hasan",
            "actor_entity_id": new_id(IdPrefix.ENTITY),
            "source_refs": (source_ref(),),
            "confidence": 0.95,
            "impact": Impact.LOW,
            "review_status": ReviewStatus.APPROVED,
            "timezone": "Europe/Istanbul",
            "due_date": "2026-09-18",
            "due_precision": DuePrecision.DAY,
        }
        with self.assertRaises(ContractError):
            Commitment(**common, notify="yes")  # type: ignore[arg-type]
        with self.assertRaises(ContractError):
            Commitment(**common, notified_at="not-a-datetime")

    def test_serialization_is_deterministic_and_uses_enum_values(self) -> None:
        memory = Memory(
            id=new_id(IdPrefix.MEMORY),
            type=MemoryType.PREFERENCE,
            summary="Short answers",
            source_refs=(source_ref(),),
            confidence=0.96,
            impact=Impact.LOW,
            review_status=ReviewStatus.AUTO,
        )

        first = dumps(memory)
        second = dumps(memory)

        self.assertEqual(first, second)
        self.assertIn('"type":"preference"', first)
        self.assertIn('"schema_version":1', first)

    def test_unknown_schema_version_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.FACT,
                summary="A fact",
                source_refs=(source_ref(),),
                confidence=0.95,
                impact=Impact.LOW,
                review_status=ReviewStatus.AUTO,
                schema_version=2,
            )

    def test_confidence_does_not_coerce_strings(self) -> None:
        with self.assertRaises(ContractError):
            Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.FACT,
                summary="A fact",
                source_refs=(source_ref(),),
                confidence="0.95",  # type: ignore[arg-type]
                impact=Impact.LOW,
                review_status=ReviewStatus.AUTO,
            )

    def test_source_requires_valid_hash_and_timezone_aware_timestamp(self) -> None:
        with self.assertRaises(ContractError):
            Source(
                id=new_id(IdPrefix.SOURCE),
                source_type=SourceType.MANUAL,
                content_sha256="not-a-hash",
                ingested_at="2026-09-16T12:00:00",
            )
        with self.assertRaises(ContractError):
            Source(
                id=new_id(IdPrefix.SOURCE),
                source_type=SourceType.MANUAL,
                content_sha256=hashlib.sha256(b"source").hexdigest(),
                ingested_at="2026-09-16T12:00:00",
            )

    def test_entity_aliases_and_linked_notes_require_non_empty_text(self) -> None:
        with self.assertRaisesRegex(ContractError, "aliases item"):
            Entity(
                id=new_id(IdPrefix.ENTITY),
                type=EntityType.PERSON,
                display_name="Hasan Usta",
                normalized_name="hasan usta",
                aliases=("",),
            )
        with self.assertRaisesRegex(ContractError, "linked_notes item"):
            Entity(
                id=new_id(IdPrefix.ENTITY),
                type=EntityType.PERSON,
                display_name="Hasan Usta",
                normalized_name="hasan usta",
                linked_notes=("",),
            )


if __name__ == "__main__":
    unittest.main()
