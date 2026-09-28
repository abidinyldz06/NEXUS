from __future__ import annotations

import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

from nexus.config import NexusConfig
from nexus.contracts import Impact, Memory, MemoryType, ReviewStatus, SourceRef
from nexus.errors import NexusIndexError
from nexus.hub.service import overview, pending_reviews, record, review_detail, search
from nexus.ids import IdPrefix, new_id
from nexus.index import rebuild_index
from nexus.review.store import ReviewStore, create_review_item
from nexus.vault import VaultRepository


class HubServiceTests(unittest.TestCase):
    def test_search_record_and_review_are_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            data = root / "private"
            source = SourceRef(
                source_id=new_id(IdPrefix.SOURCE),
                conversation_id="konusma-1",
                span_ids=("msg-1",),
                span_sha256=sha256(b"msg-1").hexdigest(),
                excerpt="NEXUS Hub kararını konuştu",
            )
            memory = Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.FACT,
                summary="NEXUS Hub planı",
                source_refs=(source,),
                confidence=0.9,
                impact=Impact.LOW,
                review_status=ReviewStatus.APPROVED,
            )
            VaultRepository(vault).commit_records((memory,), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, data / "nexus.db")
            item = create_review_item(
                candidate_kind="memory",
                candidate={"summary": "Yeni aday"},
                reason_codes=("needs_review",),
                source_refs=(source,),
            )
            ReviewStore(data).enqueue(item)
            config = NexusConfig.from_mapping({"vault_path": str(vault), "data_path": str(data)})
            before = {path: (path.stat().st_size, path.stat().st_mtime_ns)
                      for path in root.rglob("*") if path.is_file()}

            state = overview(config)
            found = search(config, "NEXUS")
            detail = record(config, memory.id)
            pending = pending_reviews(config)
            review = review_detail(config, item.id)

            self.assertEqual(1, state["index"]["records"])
            self.assertEqual(1, state["review"]["pending"])
            self.assertEqual(memory.id, found["items"][0]["id"])
            self.assertTrue(detail["canonical_verified"])
            self.assertFalse(detail["original_source_verified"])
            self.assertEqual(source.excerpt, detail["source_refs"][0]["excerpt"])
            self.assertEqual(1, pending["total"])
            self.assertEqual(item.id, review["id"])
            after = {path: (path.stat().st_size, path.stat().st_mtime_ns)
                     for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_changed_canonical_record_is_not_presented_as_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            source = SourceRef(
                source_id=new_id(IdPrefix.SOURCE),
                conversation_id="konusma-2",
                span_ids=("msg-2",),
                span_sha256=sha256(b"msg-2").hexdigest(),
            )
            memory = Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.FACT,
                summary="Örnek karar",
                source_refs=(source,),
                confidence=0.9,
                impact=Impact.LOW,
                review_status=ReviewStatus.APPROVED,
            )
            VaultRepository(vault).commit_records((memory,), run_id=new_id(IdPrefix.RUN))
            config = NexusConfig.from_mapping({
                "vault_path": str(vault), "data_path": str(root / "private")
            })
            rebuild_index(vault, config.index_path)
            path = next((vault / "Nexus" / "Memory").rglob("*.md"))
            path.write_text(path.read_text(encoding="utf-8") + "\nDeğişti\n", encoding="utf-8")

            with self.assertRaisesRegex(NexusIndexError, "uyuşmuyor"):
                record(config, memory.id)


if __name__ == "__main__":
    unittest.main()
