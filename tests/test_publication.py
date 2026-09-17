from __future__ import annotations

import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from nexus.config import NexusConfig
from nexus.contracts import SourceRef
from nexus.errors import NexusIndexError, PublicationError, ReviewStoreError
from nexus.ids import IdPrefix, new_id
from nexus.index import rebuild_index, search_index
from nexus.publication import apply_publication, plan_publication
from nexus.review import ReviewStore, create_review_item
from nexus.vault import extract_record_payload


def _config(root: Path) -> NexusConfig:
    vault = root / "vault"
    vault.mkdir()
    return NexusConfig.from_mapping(
        {
            "vault_path": str(vault),
            "data_path": str(root / "private"),
        }
    )


def _approved_memory(config: NexusConfig, *, kind: str = "memory"):
    span_id = "msg_1"
    store = ReviewStore(config.data_path)
    item = store.enqueue(
        create_review_item(
            candidate_kind=kind,
            candidate={
                "statement": "Kullanıcı kısa ve açık yanıtları tercih ediyor.",
                "memory_type": "preference",
                "confidence": 0.96,
                "impact": "low",
                "entity_ids": [],
                "extractor": {"model": "fixture"},
            },
            reason_codes=("operator_review",),
            source_refs=(
                SourceRef(
                    source_id=new_id(IdPrefix.SOURCE),
                    conversation_id="conversation-1",
                    span_ids=(span_id,),
                    span_sha256=sha256(span_id.encode()).hexdigest(),
                ),
            ),
        )
    )
    return store.decide(item.id, action="approve", reason="Kaynak doğrulandı")


class PublicationTests(unittest.TestCase):
    def test_dry_run_is_read_only_and_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_memory(config)
            assert config.vault_path is not None

            plan = plan_publication(config, item.id)
            self.assertFalse(plan.already_published)
            self.assertFalse((config.vault_path / "Nexus").exists())

            result = apply_publication(config, item.id, confirmation=item.id)

            record_path = (
                config.vault_path
                / "Nexus/Memory/Preferences"
                / f"{result.record_id}.md"
            )
            payload = extract_record_payload(record_path.read_text(encoding="utf-8"))
            self.assertEqual(item.id, payload["extractor"]["review_id"])
            self.assertEqual(
                item.source_refs[0].span_sha256,
                payload["source_refs"][0]["span_sha256"],
            )
            self.assertEqual(1, len(search_index(config.index_path, "kısa açık")))
            view = (config.vault_path / "Nexus/Views/Current-Memory.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(result.record_id, view)
            replayed = ReviewStore(config.data_path).get(item.id)
            self.assertEqual(result.record_id, replayed.publication["record_id"])
            audits_before = tuple((config.vault_path / "Nexus/Audit/Runs").glob("*.json"))

            repeated = apply_publication(config, item.id, confirmation=item.id)

            self.assertTrue(repeated.already_published)
            self.assertFalse(repeated.writes_performed)
            self.assertEqual(
                audits_before,
                tuple((config.vault_path / "Nexus/Audit/Runs").glob("*.json")),
            )

    def test_publish_refuses_unapproved_unsupported_and_wrong_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            pending_store = ReviewStore(config.data_path)
            pending = pending_store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={"statement": "Eksik yayın adayı"},
                    reason_codes=("operator_review",),
                    source_refs=(
                        SourceRef(
                            source_id=new_id(IdPrefix.SOURCE),
                            conversation_id="conversation-2",
                            span_ids=("msg_2",),
                            span_sha256=sha256(b"msg_2").hexdigest(),
                        ),
                    ),
                )
            )
            with self.assertRaisesRegex(PublicationError, "approved or edited"):
                plan_publication(config, pending.id)

            unsupported = _approved_memory(config, kind="entity")
            with self.assertRaisesRegex(PublicationError, "memory review items only"):
                plan_publication(config, unsupported.id)

            approved = _approved_memory(config)
            with self.assertRaisesRegex(PublicationError, "exactly match"):
                apply_publication(config, approved.id, confirmation=new_id(IdPrefix.REVIEW))

    def test_index_failure_rolls_back_new_record_and_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_memory(config)
            assert config.vault_path is not None
            rebuild_index(config.vault_path, config.index_path)
            index_before = config.index_path.read_bytes()

            def failing_rebuild(vault_path: Path, index_path: Path):
                raise NexusIndexError("injected rebuild failure")

            with self.assertRaisesRegex(PublicationError, "was rolled back"):
                apply_publication(
                    config,
                    item.id,
                    confirmation=item.id,
                    rebuild=failing_rebuild,
                )

            record_id = f"mem_{item.id.removeprefix('rev_')}"
            self.assertFalse(
                (config.vault_path / "Nexus/Memory/Preferences" / f"{record_id}.md").exists()
            )
            self.assertFalse((config.vault_path / "Nexus/Views/Current-Memory.md").exists())
            self.assertEqual(index_before, config.index_path.read_bytes())
            self.assertIsNone(ReviewStore(config.data_path).get(item.id).publication)

    def test_retry_recovers_a_missing_review_publication_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_memory(config)

            with patch.object(
                ReviewStore,
                "record_publication",
                side_effect=ReviewStoreError("injected audit failure"),
            ):
                with self.assertRaisesRegex(PublicationError, "audit is incomplete"):
                    apply_publication(config, item.id, confirmation=item.id)

            self.assertIsNone(ReviewStore(config.data_path).get(item.id).publication)
            recovered = apply_publication(config, item.id, confirmation=item.id)

            self.assertTrue(recovered.already_published)
            self.assertTrue(recovered.writes_performed)
            self.assertFalse(recovered.vault_writes)
            event_lines = (config.data_path / "review/events-v1.jsonl").read_text().splitlines()
            actions = [json.loads(line)["action"] for line in event_lines]
            self.assertEqual(1, actions.count("publish"))


if __name__ == "__main__":
    unittest.main()
