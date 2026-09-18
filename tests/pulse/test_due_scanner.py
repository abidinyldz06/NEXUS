from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from nexus.contracts import Commitment, DuePrecision, Impact, ReviewStatus, SourceRef
from nexus.errors import NexusIndexError, PulseError
from nexus.ids import IdPrefix, new_id
from nexus.index import rebuild_index
from nexus.pulse import emit_due_reminders
from nexus.vault import VaultRepository, extract_record_payload


def due_commitment(index: int) -> Commitment:
    span_id = f"msg_{index}"
    return Commitment(
        id=new_id(IdPrefix.COMMITMENT),
        summary=f"Cuma Hasan Usta'yı ara {index}",
        actor_entity_id=new_id(IdPrefix.ENTITY),
        source_refs=(
            SourceRef(
                source_id=new_id(IdPrefix.SOURCE),
                conversation_id=f"conversation-{index}",
                span_ids=(span_id,),
                span_sha256=sha256(span_id.encode()).hexdigest(),
            ),
        ),
        confidence=0.98,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        timezone="Europe/Istanbul",
        due_date="2026-09-18",
        due_precision=DuePrecision.DAY,
        notify=True,
        extractor={"model": "fixture"},
    )


class DueScannerTests(unittest.TestCase):
    def test_due_commitment_emits_once_with_source_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            repository = VaultRepository(vault)
            item = due_commitment(1)
            repository.commit_records((item,), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, index)
            now = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)

            first = emit_due_reminders(vault, index, now=now)
            second = emit_due_reminders(vault, index, now=now)

            self.assertIn(item.summary, first)
            self.assertIn(item.source_refs[0].source_id, first)
            self.assertIn(item.source_refs[0].span_ids[0], first)
            self.assertEqual("", second)
            payload = extract_record_payload(
                (vault / repository.record_path(item)).read_text(encoding="utf-8")
            )
            self.assertEqual("2026-09-18T06:00:00Z", payload["notified_at"])
            self.assertEqual({"model": "fixture"}, payload["extractor"])

    def test_digest_marks_at_most_twenty_items_per_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            items = tuple(due_commitment(value) for value in range(21))
            VaultRepository(vault).commit_records(items, run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, index)
            now = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)

            first = emit_due_reminders(vault, index, now=now)
            second = emit_due_reminders(vault, index, now=now)
            third = emit_due_reminders(vault, index, now=now)

            self.assertTrue(first.startswith("NEXUS hatırlatmaları (20)"))
            self.assertTrue(second.startswith("NEXUS hatırlatmaları (1)"))
            self.assertEqual("", third)

    def test_rebuild_failure_restores_exact_canonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            repository = VaultRepository(vault)
            item = due_commitment(1)
            repository.commit_records((item,), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, index)
            path = vault / repository.record_path(item)
            original = path.read_bytes()
            now = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)

            with (
                patch(
                    "nexus.pulse.due_scanner.rebuild_index",
                    side_effect=NexusIndexError("injected rebuild failure"),
                ),
                self.assertRaisesRegex(PulseError, "rolled back"),
            ):
                emit_due_reminders(vault, index, now=now)

            self.assertEqual(original, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
