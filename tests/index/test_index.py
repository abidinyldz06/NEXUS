from __future__ import annotations

import importlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from nexus.contracts import (
    Commitment,
    CommitmentStatus,
    DuePrecision,
    Impact,
    Memory,
    MemoryType,
    ReviewStatus,
    SourceRef,
)
from nexus.errors import NexusIndexError
from nexus.ids import IdPrefix, new_id
from nexus.index import IndexStore, rebuild_index, search_index
from nexus.vault import VaultRepository


def source_ref(index: int) -> SourceRef:
    span_id = f"msg_{index}"
    return SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id=f"konusma-{index}",
        span_ids=(span_id,),
        span_sha256=sha256(span_id.encode()).hexdigest(),
        excerpt="İstanbul'da kahve toplantısı",
    )


def memory(index: int, summary: str) -> Memory:
    return Memory(
        id=new_id(IdPrefix.MEMORY),
        type=MemoryType.FACT,
        summary=summary,
        source_refs=(source_ref(index),),
        confidence=0.96,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
    )


def commitment(index: int, summary: str, *, status: str = "open") -> Commitment:
    return Commitment(
        id=new_id(IdPrefix.COMMITMENT),
        summary=summary,
        actor_entity_id=new_id(IdPrefix.ENTITY),
        source_refs=(source_ref(index),),
        confidence=0.97,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        timezone="Europe/Istanbul",
        due_date="2026-09-18",
        due_precision=DuePrecision.DAY,
        status=CommitmentStatus(status),
        notify=True,
    )


class IndexTests(unittest.TestCase):
    def test_migration_is_idempotent_and_records_current_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nexus.db"
            with IndexStore(path) as store:
                self.assertEqual(1, store.migrate())
                self.assertEqual(1, store.migrate())
                self.assertEqual(
                    1,
                    store.connection.execute("SELECT version FROM schema_version").fetchone()[0],
                )

    def test_migration_uses_the_active_plugin_package_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nexus.db"
            with (
                patch(
                    "nexus.migrations.runner.importlib.import_module",
                    wraps=importlib.import_module,
                ) as loader,
                IndexStore(path) as store,
            ):
                store.migrate()

            loader.assert_any_call(".001_initial", package="nexus.migrations")

    def test_delete_and_rebuild_preserves_canonical_hashes_and_open_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            repository = VaultRepository(vault)
            records = (
                memory(1, "Türk kahvesi tercihi"),
                commitment(2, "Cuma günü Hasan Usta'yı ara"),
                commitment(3, "Tamamlanmış iş", status="done"),
            )
            repository.commit_records(records, run_id=new_id(IdPrefix.RUN))

            first = rebuild_index(vault, index)
            with closing(sqlite3.connect(index)) as connection:
                first_rows = connection.execute(
                    "SELECT id, content_sha256 FROM records ORDER BY id"
                ).fetchall()
            index.unlink()
            second = rebuild_index(vault, index)
            with closing(sqlite3.connect(index)) as connection:
                second_rows = connection.execute(
                    "SELECT id, content_sha256 FROM records ORDER BY id"
                ).fetchall()

            self.assertEqual(3, first.records)
            self.assertEqual(1, first.open_commitments)
            self.assertEqual(first.records, second.records)
            self.assertEqual(first.open_commitments, second.open_commitments)
            self.assertEqual(first_rows, second_rows)
            self.assertEqual(0o600, index.stat().st_mode & 0o777)

    def test_turkish_search_is_literal_parameterized_and_filterable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            repository = VaultRepository(vault)
            preferred = memory(1, "Kullanıcı Türk kahvesini şekersiz tercih ediyor")
            task = commitment(2, "İstanbul toplantısını planla")
            repository.commit_records((preferred, task), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, index)

            results = search_index(index, "Türk kahvesini")
            self.assertEqual([preferred.id], [item.record_id for item in results])
            self.assertEqual("memory", results[0].kind)
            self.assertIn("[Türk]", results[0].snippet)
            self.assertEqual((), search_index(index, "Türk kahvesini", kind="commitment"))
            self.assertEqual(
                [task.id],
                [
                    item.record_id
                    for item in search_index(index, "İstanbul", kind="commitment")
                ],
            )

            hostile = search_index(index, 'İstanbul" OR *; DROP TABLE records; --')
            self.assertEqual((), hostile)
            self.assertIn(task.id, [item.record_id for item in search_index(index, "İstanbul")])

    def test_extractor_metadata_does_not_create_false_content_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            repository = VaultRepository(vault)
            game = memory(1, "Total War oyununu seviyor")
            game = Memory(
                id=game.id,
                type=game.type,
                summary=game.summary,
                source_refs=game.source_refs,
                confidence=game.confidence,
                impact=game.impact,
                review_status=game.review_status,
                extractor={"pipeline": "nexus-ingest-v2"},
            )
            project = memory(2, "NEXUS Hub planını hazırla")
            repository.commit_records((game, project), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, index)

            self.assertEqual(
                [project.id], [item.record_id for item in search_index(index, "NEXUS")]
            )
            self.assertEqual(
                [game.id], [item.record_id for item in search_index(index, "Total War")]
            )

    def test_legacy_search_profile_requires_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            index = root / "private" / "nexus.db"
            repository = VaultRepository(vault)
            item = memory(1, "NEXUS Hub planı")
            repository.commit_records((item,), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, index)
            with closing(sqlite3.connect(index)) as connection:
                connection.execute("DROP TABLE search_profile")

            with self.assertRaisesRegex(NexusIndexError, "run rebuild"):
                search_index(index, "NEXUS")
            rebuild_index(vault, index)
            self.assertEqual(
                [item.id], [result.record_id for result in search_index(index, "NEXUS")]
            )

    def test_empty_query_and_missing_index_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with self.assertRaises(NexusIndexError):
                search_index(path, "kahve")
            with self.assertRaises(NexusIndexError):
                search_index(path, "***")

    def test_nested_canonical_symlink_fails_closed(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(directory)
            vault = root / "vault"
            facts = vault / "Nexus" / "Memory"
            facts.mkdir(parents=True)
            (facts / "Facts").symlink_to(Path(outside), target_is_directory=True)

            with self.assertRaisesRegex(NexusIndexError, "symlink"):
                rebuild_index(vault, root / "private" / "nexus.db")
            self.assertFalse((root / "private").exists())

    def test_search_query_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.db"
            with self.assertRaisesRegex(NexusIndexError, "500 characters"):
                search_index(path, "a" * 501)


if __name__ == "__main__":
    unittest.main()
