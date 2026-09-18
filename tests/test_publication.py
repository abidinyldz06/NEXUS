from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from nexus.config import NexusConfig
from nexus.contracts import Entity, EntityType, SourceRef
from nexus.errors import NexusIndexError, PublicationError, ReviewStoreError
from nexus.ids import IdPrefix, new_id
from nexus.index import rebuild_index, search_index
from nexus.ingest import stage_inbox_source
from nexus.publication import apply_publication, plan_publication
from nexus.pulse import scan_due_commitments
from nexus.raw_store import discover_inbox
from nexus.review import ReviewStore, create_review_item
from nexus.vault import VaultRepository, extract_record_payload


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


def _approved_commitment(config: NexusConfig):
    assert config.vault_path is not None
    span_id = "msg_commitment"
    source_ref = SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id="conversation-commitment",
        span_ids=(span_id,),
        span_sha256=sha256(span_id.encode()).hexdigest(),
    )
    actor_id = new_id(IdPrefix.ENTITY)
    target_id = new_id(IdPrefix.ENTITY)
    VaultRepository(config.vault_path).commit_records(
        (
            Entity(
                id=actor_id,
                type=EntityType.PERSON,
                display_name="Sentetik Kullanıcı",
                normalized_name="sentetik kullanıcı",
                source_refs=(source_ref,),
            ),
            Entity(
                id=target_id,
                type=EntityType.PERSON,
                display_name="Hasan Usta",
                normalized_name="hasan usta",
                source_refs=(source_ref,),
            ),
        ),
        run_id=new_id(IdPrefix.RUN),
    )
    store = ReviewStore(config.data_path)
    item = store.enqueue(
        create_review_item(
            candidate_kind="commitment",
            candidate={
                "statement": "18 Eylül 2026 tarihinde Hasan Usta'yı ara.",
                "actor_entity_id": actor_id,
                "confidence": 0.97,
                "impact": "low",
                "timezone": "Europe/Istanbul",
                "due_date": "2026-09-18",
                "due_time": None,
                "due_precision": "day",
                "target_entity_ids": [target_id],
                "notify": True,
                "extractor": {"model": "fixture"},
            },
            reason_codes=("operator_review",),
            source_refs=(source_ref,),
        )
    )
    return store.decide(item.id, action="approve", reason="Commitment doğrulandı")


def _approved_entity(
    config: NexusConfig,
    *,
    display_name: str = "Hasan Usta",
    linked_notes: list[str] | None = None,
):
    span_id = "msg_entity"
    store = ReviewStore(config.data_path)
    item = store.enqueue(
        create_review_item(
            candidate_kind="entity",
            candidate={
                "display_name": display_name,
                "normalized_name": display_name.casefold(),
                "entity_type": "person",
                "aliases": [],
                "linked_notes": linked_notes or [],
                "extractor": {"model": "fixture"},
            },
            reason_codes=("operator_review",),
            source_refs=(
                SourceRef(
                    source_id=new_id(IdPrefix.SOURCE),
                    conversation_id="conversation-entity",
                    span_ids=(span_id,),
                    span_sha256=sha256(span_id.encode()).hexdigest(),
                ),
            ),
        )
    )
    return store.decide(item.id, action="approve", reason="Entity doğrulandı")


def _approved_relation(
    config: NexusConfig,
    *,
    from_entity_id: str | None = None,
    to_entity_id: str | None = None,
    predicate: str = "works_at",
    literal: str | None = None,
    statement: str = "Ayşe NEXUS projesinde çalışıyor.",
):
    assert config.vault_path is not None
    span_id = "msg_relation"
    source_ref = SourceRef(
        source_id=new_id(IdPrefix.SOURCE),
        conversation_id="conversation-relation",
        span_ids=(span_id,),
        span_sha256=sha256(span_id.encode()).hexdigest(),
    )
    if from_entity_id is None:
        from_entity_id = new_id(IdPrefix.ENTITY)
        VaultRepository(config.vault_path).commit_records(
            (
                Entity(
                    id=from_entity_id,
                    type=EntityType.PERSON,
                    display_name="Ayşe",
                    normalized_name="ayşe",
                    source_refs=(source_ref,),
                ),
            ),
            run_id=new_id(IdPrefix.RUN),
        )
    if to_entity_id is None and literal is None:
        to_entity_id = new_id(IdPrefix.ENTITY)
        VaultRepository(config.vault_path).commit_records(
            (
                Entity(
                    id=to_entity_id,
                    type=EntityType.PROJECT,
                    display_name="NEXUS",
                    normalized_name="nexus",
                    source_refs=(source_ref,),
                ),
            ),
            run_id=new_id(IdPrefix.RUN),
        )
    store = ReviewStore(config.data_path)
    item = store.enqueue(
        create_review_item(
            candidate_kind="relation",
            candidate={
                "statement": statement,
                "from_entity_id": from_entity_id,
                "predicate": predicate,
                "to_entity_id": to_entity_id,
                "literal": literal,
                "confidence": 0.97,
                "impact": "low",
                "extractor": {"model": "fixture"},
            },
            reason_codes=("operator_review",),
            source_refs=(source_ref,),
        )
    )
    return store.decide(item.id, action="approve", reason="Relation doğrulandı")


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

    def test_commitment_publish_is_exact_confirmed_indexed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_commitment(config)
            assert config.vault_path is not None

            plan = plan_publication(config, item.id)
            self.assertEqual("commitment", plan.record_kind)
            self.assertFalse(plan.already_published)

            result = apply_publication(config, item.id, confirmation=item.id)
            record_path = config.vault_path / "Nexus/Commitments" / f"{result.record_id}.md"
            payload = extract_record_payload(record_path.read_text(encoding="utf-8"))
            due = scan_due_commitments(
                config.index_path,
                now=datetime(2026, 9, 18, 12, tzinfo=ZoneInfo("Europe/Istanbul")),
            )

            self.assertEqual("commitment", result.record_kind)
            self.assertEqual(item.id, payload["extractor"]["review_id"])
            self.assertEqual(result.record_id, due[0].commitment.id)
            self.assertFalse((config.vault_path / "Nexus/Views/Current-Memory.md").exists())
            repeated = apply_publication(config, item.id, confirmation=item.id)
            self.assertTrue(repeated.already_published)
            self.assertFalse(repeated.writes_performed)

    def test_commitment_index_failure_rolls_back_new_record_without_memory_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_commitment(config)
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

            record_id = f"com_{item.id.removeprefix('rev_')}"
            self.assertFalse(
                (config.vault_path / "Nexus/Commitments" / f"{record_id}.md").exists()
            )
            self.assertFalse((config.vault_path / "Nexus/Views/Current-Memory.md").exists())
            self.assertEqual(index_before, config.index_path.read_bytes())
            self.assertIsNone(ReviewStore(config.data_path).get(item.id).publication)

    def test_entity_publish_is_indexed_idempotent_and_has_no_memory_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_entity(config)
            assert config.vault_path is not None

            plan = plan_publication(config, item.id)
            result = apply_publication(config, item.id, confirmation=item.id)
            record_path = (
                config.vault_path / "Nexus/Entities/People" / f"{result.record_id}.md"
            )
            payload = extract_record_payload(record_path.read_text(encoding="utf-8"))

            self.assertEqual("entity", plan.record_kind)
            self.assertEqual("entity", result.record_kind)
            self.assertEqual("Hasan Usta", payload["display_name"])
            self.assertEqual(1, len(search_index(config.index_path, "Hasan Usta")))
            self.assertFalse((config.vault_path / "Nexus/Views/Current-Memory.md").exists())
            repeated = apply_publication(config, item.id, confirmation=item.id)
            self.assertTrue(repeated.already_published)
            self.assertFalse(repeated.writes_performed)

    def test_entity_publish_rejects_exact_typed_alias_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            first = _approved_entity(config)
            apply_publication(config, first.id, confirmation=first.id)
            duplicate = _approved_entity(config, display_name="HASAN USTA")

            with self.assertRaisesRegex(PublicationError, "exact typed alias"):
                plan_publication(config, duplicate.id)

    def test_entity_publish_rejects_exact_typed_linked_note_collision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            first = _approved_entity(
                config,
                display_name="Hasan Usta",
                linked_notes=["Kisiler/Hasan-Usta.md"],
            )
            apply_publication(config, first.id, confirmation=first.id)
            duplicate = _approved_entity(
                config,
                display_name="H. Usta",
                linked_notes=["Kisiler/Hasan-Usta.md"],
            )

            with self.assertRaisesRegex(PublicationError, "linked note"):
                plan_publication(config, duplicate.id)

    def test_staged_entity_can_be_human_completed_and_published(self) -> None:
        class EntityLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_id = envelope["spans"][0]["span_id"]
                return SimpleNamespace(
                    parsed={
                        "schema_version": 1,
                        "candidates": [
                            {
                                "kind": "entity",
                                "statement": "Hasan Usta kişisi.",
                                "entity_mentions": ["Hasan Usta"],
                                "temporal_expression": None,
                                "source_span_ids": [span_id],
                                "confidence": 0.97,
                                "ambiguity_flags": [],
                                "possible_supersedes": [],
                            }
                        ],
                        "ignored_span_ids": [],
                        "warnings": [],
                    },
                    provider="fixture-provider",
                    model="fixture-model",
                    agent_id="fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = _config(root)
            inbox = root / "inbox"
            inbox.mkdir()
            config = NexusConfig(
                vault_path=config.vault_path,
                inbox_path=inbox,
                data_path=config.data_path,
                source_stable_seconds=1,
            )
            note = inbox / "entity.md"
            note.write_text("Hasan Usta benim tesisatçım.", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            stage_inbox_source(
                config,
                EntityLlm(),
                relative_path=note.name,
                confirmed_sha256=discovered.content_sha256,
            )
            store = ReviewStore(config.data_path)
            pending = store.list()[0]
            completed = dict(pending.candidate)
            completed["entity_type"] = "person"
            edited = store.decide(
                pending.id,
                action="edit",
                reason="Entity türü doğrulandı",
                edited_candidate=completed,
            )

            result = apply_publication(config, edited.id, confirmation=edited.id)

            self.assertEqual("entity", result.record_kind)
            self.assertEqual(1, len(search_index(config.index_path, "Hasan Usta")))

    def test_relation_publish_is_indexed_idempotent_and_has_no_memory_view(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_relation(config)
            assert config.vault_path is not None

            plan = plan_publication(config, item.id)
            result = apply_publication(config, item.id, confirmation=item.id)
            record_path = config.vault_path / "Nexus/Relations" / f"{result.record_id}.md"
            payload = extract_record_payload(record_path.read_text(encoding="utf-8"))

            self.assertEqual("relation", plan.record_kind)
            self.assertEqual("relation", result.record_kind)
            self.assertEqual("works_at", payload["predicate"])
            self.assertEqual(1, len(search_index(config.index_path, "works_at")))
            self.assertFalse((config.vault_path / "Nexus/Views/Current-Memory.md").exists())
            repeated = apply_publication(config, item.id, confirmation=item.id)
            self.assertTrue(repeated.already_published)
            self.assertFalse(repeated.writes_performed)

    def test_relation_publish_rejects_duplicate_and_non_allowlisted_literal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            first = _approved_relation(config)
            result = apply_publication(config, first.id, confirmation=first.id)
            assert config.vault_path is not None
            payload = extract_record_payload(
                (config.vault_path / "Nexus/Relations" / f"{result.record_id}.md").read_text(
                    encoding="utf-8"
                )
            )
            duplicate = _approved_relation(
                config,
                from_entity_id=payload["from_entity_id"],
                to_entity_id=payload["to_entity_id"],
                statement="NEXUS projesinde çalışan Ayşe.",
            )

            with self.assertRaisesRegex(PublicationError, "duplicates"):
                plan_publication(config, duplicate.id)

            invalid_literal = _approved_relation(
                config,
                from_entity_id=payload["from_entity_id"],
                predicate="owns",
                literal="araba",
            )
            with self.assertRaisesRegex(PublicationError, "does not allow a literal"):
                plan_publication(config, invalid_literal.id)

            invalid_predicate_type = _approved_relation(
                config,
                from_entity_id=payload["from_entity_id"],
                to_entity_id=payload["to_entity_id"],
                predicate=["works_at"],  # type: ignore[arg-type]
            )
            with self.assertRaisesRegex(PublicationError, "not allowlisted"):
                plan_publication(config, invalid_predicate_type.id)

    def test_relation_publish_rejects_missing_canonical_entity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            item = _approved_relation(
                config,
                from_entity_id=new_id(IdPrefix.ENTITY),
                to_entity_id=new_id(IdPrefix.ENTITY),
            )

            with self.assertRaisesRegex(PublicationError, "missing canonical entity"):
                plan_publication(config, item.id)

    def test_staged_relation_can_be_human_completed_and_published(self) -> None:
        class RelationLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_id = envelope["spans"][0]["span_id"]
                return SimpleNamespace(
                    parsed={
                        "schema_version": 1,
                        "candidates": [
                            {
                                "kind": "relation",
                                "statement": "Ayşe NEXUS projesinde çalışıyor.",
                                "entity_mentions": ["Ayşe", "NEXUS"],
                                "temporal_expression": None,
                                "source_span_ids": [span_id],
                                "confidence": 0.97,
                                "ambiguity_flags": [],
                                "possible_supersedes": [],
                            }
                        ],
                        "ignored_span_ids": [],
                        "warnings": [],
                    },
                    provider="fixture-provider",
                    model="fixture-model",
                    agent_id="fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = _config(root)
            inbox = root / "inbox"
            inbox.mkdir()
            config = NexusConfig(
                vault_path=config.vault_path,
                inbox_path=inbox,
                data_path=config.data_path,
                source_stable_seconds=1,
            )
            note = inbox / "relation.md"
            note.write_text("Ayşe NEXUS projesinde çalışıyor.", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            stage_inbox_source(
                config,
                RelationLlm(),
                relative_path=note.name,
                confirmed_sha256=discovered.content_sha256,
            )
            store = ReviewStore(config.data_path)
            pending = store.list()[0]
            from_entity_id = new_id(IdPrefix.ENTITY)
            to_entity_id = new_id(IdPrefix.ENTITY)
            assert config.vault_path is not None
            VaultRepository(config.vault_path).commit_records(
                (
                    Entity(
                        id=from_entity_id,
                        type=EntityType.PERSON,
                        display_name="Ayşe",
                        normalized_name="ayşe",
                        source_refs=pending.source_refs,
                    ),
                    Entity(
                        id=to_entity_id,
                        type=EntityType.PROJECT,
                        display_name="NEXUS",
                        normalized_name="nexus",
                        source_refs=pending.source_refs,
                    ),
                ),
                run_id=new_id(IdPrefix.RUN),
            )
            completed = dict(pending.candidate)
            completed.update(
                {
                    "from_entity_id": from_entity_id,
                    "predicate": "works_at",
                    "to_entity_id": to_entity_id,
                }
            )
            edited = store.decide(
                pending.id,
                action="edit",
                reason="Relation uçları ve predicate doğrulandı",
                edited_candidate=completed,
            )

            result = apply_publication(config, edited.id, confirmation=edited.id)

            self.assertEqual("relation", result.record_kind)
            self.assertEqual(1, len(search_index(config.index_path, "works_at")))

    def test_staged_commitment_can_be_human_completed_and_published(self) -> None:
        class CommitmentLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_id = envelope["spans"][0]["span_id"]
                return SimpleNamespace(
                    parsed={
                        "schema_version": 1,
                        "candidates": [
                            {
                                "kind": "commitment",
                                "statement": "Cuma Hasan Usta'yı aramam lazım.",
                                "entity_mentions": ["Hasan Usta"],
                                "temporal_expression": "Cuma",
                                "source_span_ids": [span_id],
                                "confidence": 0.97,
                                "ambiguity_flags": [],
                                "possible_supersedes": [],
                            }
                        ],
                        "ignored_span_ids": [],
                        "warnings": [],
                    },
                    provider="fixture-provider",
                    model="fixture-model",
                    agent_id="fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = _config(root)
            inbox = root / "inbox"
            inbox.mkdir()
            config = NexusConfig(
                vault_path=config.vault_path,
                inbox_path=inbox,
                data_path=config.data_path,
                source_stable_seconds=1,
            )
            note = inbox / "commitment.md"
            note.write_text("Cuma Hasan Usta'yı aramam lazım.", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            stage_inbox_source(
                config,
                CommitmentLlm(),
                relative_path=note.name,
                confirmed_sha256=discovered.content_sha256,
            )
            store = ReviewStore(config.data_path)
            pending = store.list()[0]
            actor_id = new_id(IdPrefix.ENTITY)
            target_id = new_id(IdPrefix.ENTITY)
            assert config.vault_path is not None
            VaultRepository(config.vault_path).commit_records(
                (
                    Entity(
                        id=actor_id,
                        type=EntityType.PERSON,
                        display_name="Sentetik Kullanıcı",
                        normalized_name="sentetik kullanıcı",
                        source_refs=pending.source_refs,
                    ),
                    Entity(
                        id=target_id,
                        type=EntityType.PERSON,
                        display_name="Hasan Usta",
                        normalized_name="hasan usta",
                        source_refs=pending.source_refs,
                    ),
                ),
                run_id=new_id(IdPrefix.RUN),
            )
            completed = dict(pending.candidate)
            completed.update(
                {
                    "actor_entity_id": actor_id,
                    "due_date": "2026-09-18",
                    "due_precision": "day",
                    "target_entity_ids": [target_id],
                    "notify": True,
                }
            )
            edited = store.decide(
                pending.id,
                action="edit",
                reason="Actor, hedef ve tarih doğrulandı",
                edited_candidate=completed,
            )

            result = apply_publication(config, edited.id, confirmation=edited.id)

            self.assertEqual("commitment", result.record_kind)
            self.assertTrue(
                (config.vault_path / "Nexus/Commitments" / f"{result.record_id}.md").is_file()
            )
            self.assertEqual(
                1,
                len(
                    scan_due_commitments(
                        config.index_path,
                        now=datetime(
                            2026, 9, 18, 12, tzinfo=ZoneInfo("Europe/Istanbul")
                        ),
                    )
                ),
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

            unsupported = _approved_memory(config, kind="correction")
            with self.assertRaisesRegex(
                PublicationError, "memory, commitment, entity or relation"
            ):
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
