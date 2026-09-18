from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from nexus.config import NexusConfig
from nexus.errors import ExtractionError, SourceError, StateError
from nexus.ingest import build_source_record
from nexus.ingest import stage_inbox_source
from nexus.raw_store import discover_inbox
from nexus.review import ReviewStore
from nexus.sources import ManualAdapter
from nexus.state import SourceStateStore


class StageLlm:
    def __init__(
        self,
        *,
        statement: str = "Kullanıcı kısa yanıtları tercih ediyor.",
        kind: str = "memory",
    ) -> None:
        self.statement = statement
        self.kind = kind
        self.calls = 0

    def complete_structured(self, **kwargs):
        self.calls += 1
        envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
        spans = envelope["spans"]
        return SimpleNamespace(
            parsed={
                "schema_version": 1,
                "candidates": [
                    {
                        "kind": self.kind,
                        "statement": self.statement,
                        "entity_mentions": [],
                        "temporal_expression": None,
                        "source_span_ids": [spans[0]["span_id"]],
                        "confidence": 0.96,
                        "ambiguity_flags": [],
                        "possible_supersedes": [],
                    }
                ],
                "ignored_span_ids": [item["span_id"] for item in spans[1:]],
                "warnings": [],
            },
            provider="fixture-provider",
            model="fixture-model",
            agent_id="fixture-agent",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
        )


class FailingLlm:
    def __init__(self) -> None:
        self.calls = 0

    def complete_structured(self, **kwargs):
        self.calls += 1
        raise RuntimeError("injected provider failure")


def _stage_config(root: Path) -> NexusConfig:
    inbox = root / "inbox"
    inbox.mkdir()
    return NexusConfig(
        vault_path=root / "vault-must-not-exist",
        inbox_path=inbox,
        data_path=root / "private",
        source_stable_seconds=1,
    )


def _source(config: NexusConfig, text: str = "Kısa yanıtları tercih ederim."):
    path = config.inbox_path / "note.md"
    path.write_text(text, encoding="utf-8")
    old = time.time() - 60
    os.utime(path, (old, old))
    return discover_inbox(config.inbox_path, stable_seconds=1).accepted[0]


class IngestMetadataTests(unittest.TestCase):
    def test_normalized_conversation_builds_versioned_source_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Sentetik tercih", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            discovered = discover_inbox(inbox, stable_seconds=1).accepted[0]
            parsed = ManualAdapter().parse_bytes(note.read_bytes(), original_name=note.name)
            conversation = parsed.conversations[0]
            observation = SourceStateStore(root / "state" / "sources.json").observe(
                source_type=parsed.source_type,
                external_id=conversation.external_conversation_id,
                content_sha256=conversation.content_sha256,
            )

            source = build_source_record(
                parsed=parsed,
                conversation_index=0,
                discovered=discovered,
                observation=observation,
                raw_locator="raw/ab/hash.md",
                retention_days=90,
                now=datetime(2026, 9, 16, tzinfo=timezone.utc),
            )

        self.assertEqual(observation.source_id, source.id)
        self.assertEqual(1, source.revision)
        self.assertEqual("note.md", source.original_name)
        self.assertEqual("2026-12-15", source.retained_until)
        self.assertEqual(conversation.content_sha256, source.content_sha256)

    def test_exact_source_stage_archives_and_enqueues_idempotently_without_vault_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _stage_config(Path(directory))
            discovered = _source(config)
            llm = StageLlm()

            first = stage_inbox_source(
                config,
                llm,
                relative_path="note.md",
                confirmed_sha256=discovered.content_sha256,
            )
            second = stage_inbox_source(
                config,
                llm,
                relative_path="note.md",
                confirmed_sha256=discovered.content_sha256,
            )

            items = ReviewStore(config.data_path).list()
            raw = config.data_path / "raw" / discovered.content_sha256[:2]
            archived = raw / f"{discovered.content_sha256}.md"
            events = (config.data_path / "review/events-v1.jsonl").read_text().splitlines()
            state = config.data_path / "state/sources-v1.json"

            self.assertEqual(1, first.review_items_created)
            self.assertEqual(0, first.review_items_reused)
            self.assertTrue(first.writes_performed)
            self.assertEqual(0, second.review_items_created)
            self.assertEqual(1, second.review_items_reused)
            self.assertFalse(second.writes_performed)
            self.assertTrue(second.duplicate_source)
            self.assertEqual(1, len(items))
            self.assertEqual("memory", items[0].candidate_kind)
            self.assertIsNone(items[0].candidate["memory_type"])
            self.assertIn("memory_type_required", items[0].reason_codes)
            self.assertEqual(1, len(events))
            self.assertTrue(archived.is_file())
            self.assertTrue(state.is_file())
            self.assertEqual(0o600, archived.stat().st_mode & 0o777)
            self.assertEqual(0o600, state.stat().st_mode & 0o777)
            self.assertFalse(config.vault_path.exists())
            self.assertEqual(2, llm.calls)

    def test_stage_rejects_wrong_sha_before_model_or_private_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _stage_config(Path(directory))
            _source(config)
            llm = StageLlm()

            with self.assertRaisesRegex(SourceError, "confirmation SHA"):
                stage_inbox_source(
                    config,
                    llm,
                    relative_path="note.md",
                    confirmed_sha256="0" * 64,
                )

            self.assertEqual(0, llm.calls)
            self.assertFalse(config.data_path.exists())

    def test_stage_finishes_all_model_calls_before_private_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _stage_config(Path(directory))
            discovered = _source(config)
            llm = FailingLlm()

            with self.assertRaises(ExtractionError):
                stage_inbox_source(
                    config,
                    llm,
                    relative_path="note.md",
                    confirmed_sha256=discovered.content_sha256,
                )

            self.assertEqual(2, llm.calls)
            self.assertFalse(config.data_path.exists())

    def test_secret_like_candidate_quarantines_source_without_review_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _stage_config(Path(directory))
            discovered = _source(config, "Bu metni güvenli biçimde değerlendir.")

            report = stage_inbox_source(
                config,
                StageLlm(statement="api_key = sk_abcdefghijklmnop1234"),
                relative_path="note.md",
                confirmed_sha256=discovered.content_sha256,
            )

            quarantined = (
                config.data_path
                / "quarantine"
                / discovered.content_sha256[:2]
                / f"{discovered.content_sha256}.md"
            )
            self.assertEqual("quarantine", report.raw_disposition)
            self.assertEqual(1, report.quarantined)
            self.assertEqual((), ReviewStore(config.data_path).list())
            self.assertTrue(quarantined.is_file())
            self.assertFalse((config.data_path / "raw").exists())

    def test_stage_rejects_symlinked_state_directory_before_private_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _stage_config(Path(directory))
            discovered = _source(config)
            config.data_path.mkdir()
            outside = Path(directory) / "outside-state"
            outside.mkdir()
            (config.data_path / "state").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(StateError, "real directory"):
                stage_inbox_source(
                    config,
                    StageLlm(),
                    relative_path="note.md",
                    confirmed_sha256=discovered.content_sha256,
                )

            self.assertEqual([], list(outside.iterdir()))
            self.assertFalse((config.data_path / "raw").exists())
            self.assertFalse((config.data_path / "quarantine").exists())

    def test_staged_commitment_has_closed_human_completion_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _stage_config(Path(directory))
            discovered = _source(config, "Cuma Hasan Usta'yı aramam lazım.")

            stage_inbox_source(
                config,
                StageLlm(
                    kind="commitment",
                    statement="Cuma Hasan Usta'yı aramam lazım.",
                ),
                relative_path="note.md",
                confirmed_sha256=discovered.content_sha256,
            )

            item = ReviewStore(config.data_path).list()[0]
            self.assertEqual("commitment", item.candidate_kind)
            self.assertEqual(
                {
                    "statement",
                    "actor_entity_id",
                    "confidence",
                    "impact",
                    "timezone",
                    "due_date",
                    "due_time",
                    "due_precision",
                    "target_entity_ids",
                    "notify",
                    "extractor",
                },
                set(item.candidate),
            )
            self.assertIsNone(item.candidate["actor_entity_id"])
            self.assertEqual("ambiguous", item.candidate["due_precision"])
            self.assertFalse(item.candidate["notify"])


if __name__ == "__main__":
    unittest.main()
