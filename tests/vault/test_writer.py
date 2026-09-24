from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from nexus.contracts import Impact, Memory, MemoryType, RecordStatus, ReviewStatus, SourceRef
from nexus.corrections import apply_memory_correction
from nexus.errors import VaultConflictError, VaultError, VaultTransactionError
from nexus.ids import IdPrefix, new_id
from nexus.vault import VaultRepository, VaultTransaction, VaultWrite, extract_record_payload
from nexus.vault.rebuild_views import current_memory_view_write


def source_ref(index: int) -> SourceRef:
    span_id = f"msg_{index}"
    return SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id=f"conversation-{index}",
        span_ids=(span_id,),
        span_sha256=sha256(span_id.encode()).hexdigest(),
        excerpt=f"Kanıt {index}",
    )


def memory(
    index: int,
    *,
    summary: str | None = None,
    supersedes: tuple[str, ...] = (),
) -> Memory:
    return Memory(
        id=new_id(IdPrefix.MEMORY),
        type=MemoryType.FACT,
        summary=summary or f"Doğrulanmış hafıza {index}",
        source_refs=(source_ref(index),),
        confidence=0.95,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        supersedes=supersedes,
        extractor={"model": "fixture"},
    )


class VaultWriterTests(unittest.TestCase):
    def test_twenty_records_round_trip_to_exact_source_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            records = tuple(memory(index) for index in range(20))
            run_id = new_id(IdPrefix.RUN)

            result = repository.commit_records(records, run_id=run_id)

            self.assertEqual(20, len(result.written_paths))
            for record in records:
                path = root / repository.record_path(record)
                payload = extract_record_payload(path.read_text(encoding="utf-8"))
                self.assertEqual(record.id, payload["id"])
                self.assertEqual(
                    list(record.source_refs[0].span_ids),
                    payload["source_refs"][0]["span_ids"],
                )
                self.assertEqual(
                    record.source_refs[0].span_sha256,
                    payload["source_refs"][0]["span_sha256"],
                )
                self.assertEqual(0o600, os.stat(path).st_mode & 0o777)
            audit = root / "Nexus" / "Audit" / "Runs" / f"{run_id}.json"
            audit_payload = json.loads(audit.read_text(encoding="utf-8"))
            self.assertEqual("committed", audit_payload["state"])
            self.assertEqual(20, len(audit_payload["writes"]))
            self.assertNotIn(records[0].summary, audit.read_text(encoding="utf-8"))
            self.assertFalse((root / "Nexus" / ".transactions" / run_id).exists())

    def test_renderer_neutralizes_markdown_html_and_round_trips_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            unsafe = memory(1, summary="</pre><script>alert(1)</script> ![[secret]]")

            repository.commit_records((unsafe,), run_id=new_id(IdPrefix.RUN))

            rendered = (root / repository.record_path(unsafe)).read_text(encoding="utf-8")
            self.assertNotIn("<script>", rendered)
            self.assertNotIn("![[secret]]", rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertEqual(unsafe.summary, extract_record_payload(rendered)["summary"])

            with self.assertRaises(VaultError):
                repository.prepare_record(
                    unsafe,
                    run_id="run_bad\nstatus: forged",
                    written_at="2026-09-17T00:00:00+03:00",
                )

    def test_memory_heading_is_claim_with_visible_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            record = memory(
                1,
                summary="# reminder wanted\nNo ping after 22:00.",
            )
            record = replace(record, type=MemoryType.PREFERENCE)
            run_id = new_id(IdPrefix.RUN)

            prepared = repository.prepare_record(
                record,
                run_id=run_id,
                written_at="2026-09-24T10:00:00+03:00",
            )
            rendered = prepared.content.decode("utf-8")

            self.assertIn("memory_type: preference", rendered)
            self.assertIn("date: 2026-09-24", rendered)
            self.assertIn("# reminder wanted No ping after 22:00.", rendered)
            self.assertNotIn("# NEXUS Memory —", rendered)
            self.assertNotIn("<script>", rendered)

    def test_memory_restyle_rewrites_generic_heading_without_changing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            record = replace(memory(1, summary="No ping after 22:00."), type=MemoryType.PREFERENCE)
            run_id = new_id(IdPrefix.RUN)
            repository.commit_records((record,), run_id=run_id)
            path = root / repository.record_path(record)
            original = path.read_text(encoding="utf-8")
            stale = original.replace("# No ping after 22:00.", "# NEXUS Memory — preference")
            path.write_text(stale, encoding="utf-8")

            restyle_run = new_id(IdPrefix.RUN)
            result = repository.restyle_existing_memories(run_id=restyle_run)
            restyled = path.read_text(encoding="utf-8")

            self.assertEqual(1, len(result.written_paths))
            self.assertIn("# No ping after 22:00.", restyled)
            self.assertIn("date: 2026-09-", restyled)
            self.assertNotIn("# NEXUS Memory —", restyled)
            self.assertEqual(
                extract_record_payload(original)["summary"],
                extract_record_payload(restyled)["summary"],
            )
            self.assertIn(f"run_id: {restyle_run}", restyled)

    def test_create_update_and_stale_precondition_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            original = memory(1)
            repository.commit_records((original,), run_id=new_id(IdPrefix.RUN))
            original_hash = repository.current_hash(original)
            updated = replace(original, summary="Güncel ifade")

            with self.assertRaises(VaultConflictError):
                repository.commit_records((updated,), run_id=new_id(IdPrefix.RUN))

            repository.commit_records(
                (updated,),
                run_id=new_id(IdPrefix.RUN),
                expected_hashes={updated.id: original_hash},
            )
            with self.assertRaises(VaultConflictError):
                repository.commit_records(
                    (replace(updated, summary="Bayat güncelleme"),),
                    run_id=new_id(IdPrefix.RUN),
                    expected_hashes={updated.id: original_hash},
                )

    def test_precondition_is_rechecked_immediately_before_replace(self) -> None:
        class RacingTransaction(VaultTransaction):
            def _before_replace(self, index, target):
                if index == 0:
                    target.write_text("external edit before replace", encoding="utf-8")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            original = memory(1)
            repository.commit_records((original,), run_id=new_id(IdPrefix.RUN))
            original_hash = repository.current_hash(original)
            updated = replace(original, summary="NEXUS update")

            with self.assertRaises(VaultTransactionError):
                repository.commit_records(
                    (updated,),
                    run_id=new_id(IdPrefix.RUN),
                    expected_hashes={original.id: original_hash},
                    transaction=RacingTransaction(root),
                )

            target = root / repository.record_path(original)
            self.assertEqual("external edit before replace", target.read_text(encoding="utf-8"))

    def test_path_escape_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            transaction = VaultTransaction(root)
            with self.assertRaises(VaultError):
                transaction.commit(
                    (VaultWrite(Path("Nexus/../outside.md"), b"unsafe"),),
                    run_id=new_id(IdPrefix.RUN),
                )

            (root / "Nexus").mkdir()
            (root / "Nexus" / "Memory").symlink_to(Path(outside), target_is_directory=True)
            record = memory(2)
            repository = VaultRepository(root)
            with self.assertRaises(VaultError):
                repository.commit_records((record,), run_id=new_id(IdPrefix.RUN))
            self.assertEqual([], list(Path(outside).iterdir()))

    def test_injected_failure_rolls_back_update_and_create(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            previous = memory(1)
            repository.commit_records((previous,), run_id=new_id(IdPrefix.RUN))
            previous_path = root / repository.record_path(previous)
            previous_bytes = previous_path.read_bytes()
            previous_hash = repository.current_hash(previous)
            replacement = memory(2, supersedes=(previous.id,))
            superseded, replacement = apply_memory_correction(previous, replacement)
            transaction = VaultTransaction(root, fault_after_writes=2)

            with self.assertRaises(VaultTransactionError):
                repository.commit_records(
                    (superseded, replacement),
                    run_id=new_id(IdPrefix.RUN),
                    expected_hashes={previous.id: previous_hash},
                    transaction=transaction,
                )

            self.assertEqual(previous_bytes, previous_path.read_bytes())
            self.assertFalse((root / repository.record_path(replacement)).exists())

    def test_rollback_preserves_concurrent_change_and_recovery_staging(self) -> None:
        class ConcurrentChangeTransaction(VaultTransaction):
            def _rollback(self, root, writes, existing, backups, committed_indexes):
                target = root / writes[committed_indexes[-1]].relative_path
                target.write_text("external concurrent change", encoding="utf-8")
                return super()._rollback(
                    root,
                    writes,
                    existing,
                    backups,
                    committed_indexes,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            record = memory(3)
            run_id = new_id(IdPrefix.RUN)
            transaction = ConcurrentChangeTransaction(root, fault_after_writes=1)

            with self.assertRaisesRegex(VaultTransactionError, "rollback was incomplete"):
                repository.commit_records(
                    (record,),
                    run_id=run_id,
                    transaction=transaction,
                )

            target = root / repository.record_path(record)
            self.assertEqual("external concurrent change", target.read_text(encoding="utf-8"))
            self.assertTrue((root / "Nexus" / ".transactions" / run_id).is_dir())

    def test_correction_keeps_history_and_view_contains_only_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = VaultRepository(root)
            previous = memory(1, summary="Eski durum")
            repository.commit_records((previous,), run_id=new_id(IdPrefix.RUN))
            previous_hash = repository.current_hash(previous)
            replacement = memory(
                2,
                summary="Güncel durum ![[unsafe]]",
                supersedes=(previous.id,),
            )
            superseded, replacement = apply_memory_correction(previous, replacement)
            view = current_memory_view_write((superseded, replacement), repository)

            repository.commit_records(
                (superseded, replacement),
                run_id=new_id(IdPrefix.RUN),
                expected_hashes={previous.id: previous_hash},
                generated_writes=(view,),
            )

            old_payload = extract_record_payload(
                (root / repository.record_path(superseded)).read_text(encoding="utf-8")
            )
            new_payload = extract_record_payload(
                (root / repository.record_path(replacement)).read_text(encoding="utf-8")
            )
            current_view = (root / "Nexus" / "Views" / "Current-Memory.md").read_text(
                encoding="utf-8"
            )
            self.assertEqual(RecordStatus.SUPERSEDED.value, old_payload["status"])
            self.assertEqual(replacement.id, old_payload["superseded_by"])
            self.assertEqual([previous.id], new_payload["supersedes"])
            self.assertIn(replacement.id, current_view)
            self.assertNotIn(previous.id, current_view)
            self.assertNotIn("![[unsafe]]", current_view)


if __name__ == "__main__":
    unittest.main()
