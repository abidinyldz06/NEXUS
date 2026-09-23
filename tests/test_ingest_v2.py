"""Ingest Pipeline v2. Temp directories only; the real export is not opened."""

from __future__ import annotations

import inspect
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from hashlib import sha256
from pathlib import Path

from nexus.cli import configure_parser, run_command
from nexus.config import NexusConfig
from nexus.contracts import MemoryType
from nexus.errors import ExtractionError, NexusIndexError
from nexus.extraction.schema import ExtractionCandidate, ExtractionResult
from nexus.fingerprints import segment_fingerprint
from nexus.ingest import shadow_inbox_source
from nexus.ingest_v2 import (
    FAILED_SEGMENT,
    LONG_UNIT_DEFAULT_SECONDS,
    IngestPaused,
    atomic_json,
    current_memories,
    ingest_log_path,
    load_checkpoint,
    load_json,
    load_ledger,
    pause_ingest,
    review_queue_path,
    run_conversation,
    service_extractor,
    set_paused,
    status_payload,
)
from nexus.normalize import NormalizedConversation, NormalizedMessage
from nexus.segmenter import (
    SEGMENTER_VERSION,
    _fallback_parts,
    normalize_for_segment_id,
    segment_conversation,
    segment_conversation_v2,
)

FAKE_SECRETS = (
    "sk-test-123456789",
    "ghp_FAKE_TOKEN_123456",
    "gho_FAKESECRETTOKEN12",
    "AIzaSyFakeTestKey1234567890abcd",
    "xoxb-1234567890-faketoken",
    "Bearer fake-secret-token",
    "api_key=FAKESECRET123",
    "OPENAI_API_KEY=sk-fake-key",
    "AWS_SECRET_ACCESS_KEY=fake-secret",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)


class BoomLlm:
    def complete_structured(self, **kwargs: object) -> object:
        raise AssertionError("extraction must not be called")


class FakeContext:
    def __init__(self, values: dict[str, object] | None = None, llm: object | None = None) -> None:
        self.values = values or {}
        self.llm = llm or BoomLlm()

    def get_config(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def message(identifier: str, role: str, content: str) -> NormalizedMessage:
    return NormalizedMessage.build(
        message_id=identifier,
        role=role,
        content=content,
        source_locator=f"test#message={identifier}",
    )


def conversation(messages: tuple[NormalizedMessage, ...], *, external_id: str = "conv-1") -> NormalizedConversation:
    return NormalizedConversation(
        external_conversation_id=external_id,
        title="Synthetic",
        participants=("assistant", "user"),
        messages=messages,
        source_locator=f"test:{external_id}",
    )


def preference(statement: str, span_id: str, *, supersedes: tuple[str, ...] = ()) -> ExtractionCandidate:
    return ExtractionCandidate(
        kind="memory",  # type: ignore[arg-type]
        statement=statement,
        entity_mentions=(),
        temporal_expression=None,
        source_span_ids=(span_id,),
        confidence=0.95,
        ambiguity_flags=(),
        possible_supersedes=supersedes,
    )


def result_for(segment: object, statement: str, *, supersedes: tuple[str, ...] = ()) -> ExtractionResult:
    span = segment.messages[0].message_id  # type: ignore[attr-defined]
    from nexus.extraction.schema import CandidateKind

    candidate = preference(statement, span, supersedes=supersedes)
    return ExtractionResult(
        candidates=(
            ExtractionCandidate(
                kind=CandidateKind.MEMORY,
                statement=candidate.statement,
                entity_mentions=(),
                temporal_expression=None,
                source_span_ids=candidate.source_span_ids,
                confidence=0.95,
                ambiguity_flags=(),
                possible_supersedes=supersedes,
            ),
        ),
        ignored_span_ids=(),
        warnings=(),
    )


def config_for(root: Path, *, enabled: bool = True) -> NexusConfig:
    vault = root / "vault"
    data = root / "data"
    vault.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    return NexusConfig.from_mapping(
        {
            "vault_path": str(vault),
            "inbox_path": str(root / "inbox"),
            "data_path": str(data),
            "ingest_pipeline_v2": enabled,
            "auto_publish_enabled": False,
        }
    )


def plaintext(root: Path) -> str:
    chunks: list[str] = []
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            chunks.append(path.read_bytes().decode("utf-8", errors="ignore"))
    return "\n".join(chunks)


class SegmenterV2Tests(unittest.TestCase):
    def test_v1_fingerprint_stays_on_the_flag_off_segmenter(self) -> None:
        source = conversation(
            (
                message("u1", "user", "bir"),
                message("a1", "assistant", "iki"),
            )
        )
        segment = segment_conversation(source)[0]
        self.assertEqual("", segment.segment_id)
        self.assertEqual(
            segment.fingerprint,
            segment_fingerprint(segment.messages, version=SEGMENTER_VERSION),
        )

    def test_messages_split_on_boundaries_and_oversized_message_falls_back(self) -> None:
        source = conversation(
            (
                message("u1", "user", "aaaa"),
                message("a1", "assistant", "bbbb"),
                message("u2", "user", "cccc"),
            )
        )
        segments = segment_conversation_v2(source, target_chars=4)
        self.assertEqual(3, len(segments))
        self.assertEqual((0, 0), (segments[0].start_message_index, segments[0].end_message_index))
        self.assertFalse(segments[0].split_fallback)

        huge = conversation((message("u1", "user", "abcdefghijKLMNO"),))
        parts = _fallback_parts("abcdefghijKLMNO", 5)
        self.assertEqual(normalize_for_segment_id("abcdefghijKLMNO"), "".join(parts))
        split = segment_conversation_v2(huge, target_chars=5)
        self.assertGreater(len(split), 1)
        self.assertTrue(all(item.split_fallback for item in split))
        self.assertEqual(len(split), len({item.segment_id for item in split}))

    def test_segment_id_is_stable_for_the_same_normalized_input(self) -> None:
        left = conversation((message("u1", "user", "alpha  \r\nbeta"),))
        right = conversation((message("u1", "user", "alpha\nbeta"),))
        left_id = segment_conversation_v2(left)[0].segment_id
        right_id = segment_conversation_v2(right)[0].segment_id
        self.assertEqual(left_id, right_id)
        self.assertEqual(left_id, segment_conversation_v2(left)[0].segment_id)
        changed = segment_conversation_v2(left, schema_version="other-schema")[0].segment_id
        self.assertNotEqual(left_id, changed)

    def test_fifty_four_short_messages_split_below_v1_timeout_blob(self) -> None:
        source = conversation(
            tuple(message(f"u{i}", "user", f"msg-{i:02d}") for i in range(54))
        )
        packed = segment_conversation_v2(source)
        self.assertGreaterEqual(len(packed), 5)
        self.assertTrue(all(len(item.messages) <= 12 for item in packed))
        self.assertEqual(54, sum(len(item.messages) for item in packed))

    def test_segment_id_stays_stable_when_content_hash_changes(self) -> None:
        left = conversation((message("u1", "user", "alpha"),))
        right = conversation((message("u1", "user", "omega"),))
        first = segment_conversation_v2(left)[0]
        second = segment_conversation_v2(right)[0]
        self.assertEqual(first.segment_id, second.segment_id)
        self.assertNotEqual(first.content_hash, second.content_hash)


class PipelineV2Tests(unittest.TestCase):
    def _run(self, root: Path, source: NormalizedConversation, extractor: object, **kwargs: object):
        return run_conversation(
            config_for(root),
            source,
            extractor,  # type: ignore[arg-type]
            canonical_memory_type=MemoryType.PREFERENCE,
            write_canonical=True,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_checkpoint_resume_does_not_reextract_completed_segments(self) -> None:
        source = conversation(
            (
                message("u1", "user", "aaaa"),
                message("a1", "assistant", "bbbb"),
                message("u2", "user", "cccc"),
            )
        )
        statements = {
            1: "Kullanıcı kısa yanıtları tercih ediyor.",
            2: "Kullanıcı sade kahveyi tercih ediyor.",
            3: "Kullanıcı erken saati tercih ediyor.",
        }

        class Extractor:
            def __init__(self) -> None:
                self.calls: list[int] = []
                self.pause = True

            def __call__(self, segment: object) -> ExtractionResult:
                index = segment.index  # type: ignore[attr-defined]
                self.calls.append(index)
                if self.pause and index == 3:
                    raise IngestPaused("deterministic stop, not SIGKILL")
                return result_for(segment, statements[index])

        extractor = Extractor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._run(root, source, extractor, target_chars=4)
            self.assertEqual("paused", first.final_status)
            self.assertEqual([1, 2, 3], extractor.calls)
            data = root / "data"
            checkpoint = load_checkpoint(data, first.ingest_id)
            assert checkpoint is not None
            statuses = [item["status"] for item in checkpoint["segments"].values()]
            self.assertIn("completed", statuses)
            self.assertIn("incomplete", statuses)
            extractor.pause = False
            before = list(extractor.calls)
            second = run_conversation(
                NexusConfig.from_mapping(
                    {
                        "vault_path": str(root / "vault"),
                        "inbox_path": str(root / "inbox"),
                        "data_path": str(data),
                        "ingest_pipeline_v2": True,
                    }
                ),
                source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
                target_chars=4,
            )
            self.assertEqual(before + [3], extractor.calls)
            self.assertEqual("completed", second.final_status)
            self.assertEqual(3, len(current_memories(load_ledger(data))))

    def test_retry_exhaustion_keeps_successful_segments(self) -> None:
        source = conversation(
            (
                message("u1", "user", "aaaa"),
                message("a1", "assistant", "bbbb"),
            )
        )

        class Extractor:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, segment: object) -> ExtractionResult:
                self.calls += 1
                if segment.index == 1:  # type: ignore[attr-defined]
                    return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")
                raise ExtractionError(
                    "structured extraction failed after 1 bounded attempt(s)",
                    failure_class="timeout",
                )

        extractor = Extractor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._run(root, source, extractor, target_chars=4)
            self.assertEqual(FAILED_SEGMENT, report.final_status)
            self.assertEqual(4, extractor.calls)
            self.assertEqual("completed", report.segment_statuses[next(iter(report.segment_statuses))])
            data = root / "data"
            checkpoint = load_checkpoint(data, report.ingest_id)
            assert checkpoint is not None
            failed = [
                item for item in checkpoint["segments"].values() if item["status"] == FAILED_SEGMENT
            ]
            self.assertEqual(1, len(failed))
            self.assertEqual(3, failed[0]["attempt_count"])
            self.assertEqual(1, len(current_memories(load_ledger(data))))

    def test_non_retryable_failure_stops_at_one_attempt(self) -> None:
        source = conversation((message("u1", "user", "aaaa"),))

        class Extractor:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, segment: object) -> ExtractionResult:
                self.calls += 1
                raise ExtractionError(
                    "structured extraction failed after 1 bounded attempt(s)",
                    failure_class="invalid_json",
                )

        extractor = Extractor()
        with tempfile.TemporaryDirectory() as directory:
            report = self._run(Path(directory), source, extractor, target_chars=4)
            self.assertEqual(1, extractor.calls)
            self.assertEqual(FAILED_SEGMENT, report.final_status)
            self.assertEqual("invalid_json", report.error_class)

    def test_duplicate_second_run_creates_no_memory(self) -> None:
        source = conversation((message("u1", "user", "kısa yanıt"),))

        class Extractor:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, segment: object) -> ExtractionResult:
                self.calls += 1
                return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        extractor = Extractor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._run(root, source, extractor)
            data = root / "data"
            second = run_conversation(
                NexusConfig.from_mapping(
                    {
                        "vault_path": str(root / "vault"),
                        "inbox_path": str(root / "inbox"),
                        "data_path": str(data),
                        "ingest_pipeline_v2": True,
                    }
                ),
                source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
            )
            self.assertEqual(1, extractor.calls)
            self.assertEqual(1, first.memories_created)
            self.assertEqual(0, second.memories_created)
            self.assertEqual(0, second.to_dict()["duplicates_created"])
            self.assertEqual("already_processed", second.final_status)
            self.assertGreater(second.duplicate_prevented_count, 0)
            self.assertEqual(1, len(current_memories(load_ledger(data))))

    def test_supersede_keeps_historical_record(self) -> None:
        first_source = conversation((message("u1", "user", "eski tercih"),), external_id="conv-old")
        second_source = conversation((message("u2", "user", "yeni tercih"),), external_id="conv-new")

        class Extractor:
            def __init__(self) -> None:
                self.prior: str | None = None

            def __call__(self, segment: object) -> ExtractionResult:
                if self.prior is None:
                    return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")
                return result_for(
                    segment,
                    "Kullanıcı sade kahveyi tercih ediyor.",
                    supersedes=(self.prior,),
                )

        extractor = Extractor()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            vault = root / "vault"
            data.mkdir()
            vault.mkdir()
            (root / "inbox").mkdir()
            mapping = {
                "vault_path": str(vault),
                "inbox_path": str(root / "inbox"),
                "data_path": str(data),
                "ingest_pipeline_v2": True,
            }
            run_conversation(
                NexusConfig.from_mapping(mapping),
                first_source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
            )
            prior = current_memories(load_ledger(data))[0]["id"]
            extractor.prior = prior
            run_conversation(
                NexusConfig.from_mapping(mapping),
                second_source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
            )
            rows = load_ledger(data)
            current = current_memories(rows)
            historical = [row for row in rows if row["status"] == "superseded"]
            self.assertEqual(1, len(current))
            self.assertEqual(1, len(historical))
            self.assertEqual([prior], current[0]["supersedes"])
            self.assertEqual(current[0]["id"], historical[0]["superseded_by"])
            files = list(vault.rglob("mem_*.md"))
            self.assertEqual(2, len(files))

    def test_scrubber_removes_fake_secrets_from_derived_surfaces(self) -> None:
        source = conversation((message("u1", "user", "gizli satır"),))

        class Extractor:
            def __call__(self, segment: object) -> ExtractionResult:
                from nexus.extraction.schema import CandidateKind

                span = segment.messages[0].message_id  # type: ignore[attr-defined]
                candidates = tuple(
                    ExtractionCandidate(
                        kind=CandidateKind.MEMORY,
                        statement=secret,
                        entity_mentions=(),
                        temporal_expression=None,
                        source_span_ids=(span,),
                        confidence=0.95,
                        ambiguity_flags=(),
                        possible_supersedes=(),
                    )
                    for secret in FAKE_SECRETS
                )
                return ExtractionResult(candidates=candidates, ignored_span_ids=(), warnings=())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._run(root, source, Extractor())
            self.assertEqual(0, report.memories_created)
            self.assertGreater(report.rejected, 0)
            blob = plaintext(root)
            for secret in FAKE_SECRETS:
                self.assertNotIn(secret, blob)
            self.assertEqual(0, len(list((root / "vault").rglob("mem_*.md"))))

    def test_mirror_failure_keeps_canonical_and_skips_sqlite_as_truth(self) -> None:
        source = conversation((message("u1", "user", "ayna"),))

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        def fail_mirror(vault: Path, index: Path) -> object:
            raise NexusIndexError("mirror failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._run(root, source, extractor, index_writer=fail_mirror)
            self.assertEqual("retry", report.mirror_status)
            self.assertTrue(report.vault_written)
            self.assertTrue(list((root / "vault").rglob("mem_*.md")))
            self.assertFalse((root / "data" / "nexus.db").exists())
            log = ingest_log_path(root / "data").read_text(encoding="utf-8")
            self.assertIn("obsidian_sqlite_retry", log)
            self.assertNotIn("Kullanıcı kısa yanıtları tercih ediyor.", log)

    def test_vault_failure_does_not_write_sqlite(self) -> None:
        source = conversation((message("u1", "user", "vault"),))
        calls = {"index": 0}

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        def index_writer(vault: Path, index: Path) -> object:
            calls["index"] += 1
            return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault-file"
            vault.write_text("not a directory", encoding="utf-8")
            data = root / "data"
            data.mkdir()
            report = run_conversation(
                NexusConfig.from_mapping(
                    {
                        "vault_path": str(vault),
                        "inbox_path": str(root / "inbox"),
                        "data_path": str(data),
                        "ingest_pipeline_v2": True,
                    }
                ),
                source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
                index_writer=index_writer,
            )
            self.assertEqual(0, calls["index"])
            self.assertFalse(report.vault_written)
            self.assertFalse((data / "nexus.db").exists())

    def test_incomplete_checkpoint_is_rejected_and_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial = root / "partial.json"
            partial.write_text("{", encoding="utf-8")
            with self.assertRaises(Exception):
                load_json(partial, kind="checkpoint")
            target = root / "real.json"
            atomic_json(target, {"complete": True, "ok": 1})
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaises(Exception):
                atomic_json(link, {"complete": True, "ok": 2})

    def test_flag_off_status_is_shadow_only_and_deletes_nothing(self) -> None:
        source = conversation((message("u1", "user", "bayrak"),))

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._run(root, source, extractor)
            checkpoint = root / "data" / "ingest" / "v2" / "checkpoints" / f"{report.ingest_id}.json"
            self.assertTrue(checkpoint.is_file())
            before = checkpoint.read_bytes()
            context = FakeContext(
                {
                    "vault_path": str(root / "vault"),
                    "data_path": str(root / "data"),
                    "inbox_path": str(root / "inbox"),
                    "ingest_pipeline_v2": False,
                }
            )
            arg_parser = __import__("argparse").ArgumentParser()
            configure_parser(arg_parser, lambda args: run_command(args, context))
            args = arg_parser.parse_args(["ingest", "status", "--json"])
            stream = io.StringIO()
            import contextlib

            with contextlib.redirect_stdout(stream):
                code = args.func(args)
            payload = json.loads(stream.getvalue())
            self.assertEqual(0, code)
            self.assertFalse(payload["ingest_pipeline_v2"])
            self.assertIn("shadow-only", payload["message"])
            self.assertFalse(payload["extraction_called"])
            self.assertEqual(before, checkpoint.read_bytes())

            enabled = FakeContext(
                {
                    "vault_path": str(root / "vault"),
                    "data_path": str(root / "data"),
                    "inbox_path": str(root / "inbox"),
                    "ingest_pipeline_v2": True,
                }
            )
            enabled_parser = __import__("argparse").ArgumentParser()
            configure_parser(enabled_parser, lambda args: run_command(args, enabled))
            status_args = enabled_parser.parse_args(["ingest", "status", report.ingest_id, "--json"])
            status_stream = io.StringIO()
            with contextlib.redirect_stdout(status_stream):
                status_code = status_args.func(status_args)
            status_payload = json.loads(status_stream.getvalue())
            self.assertEqual(0, status_code)
            self.assertEqual(report.ingest_id, status_payload["ingests"][0]["ingest_id"])
            self.assertNotIn("Kullanıcı kısa yanıtları tercih ediyor.", status_stream.getvalue())

    def test_flag_off_shadow_keeps_90_second_three_attempt_defaults(self) -> None:
        signature = inspect.signature(shadow_inbox_source)
        self.assertEqual(90, signature.parameters["timeout_seconds"].default)
        self.assertEqual(3, signature.parameters["max_attempts"].default)

        class CaptureLlm:
            def __init__(self) -> None:
                self.timeouts: list[float] = []

            def complete_structured(self, **kwargs: object) -> object:
                self.timeouts.append(float(kwargs["timeout"]))  # type: ignore[arg-type]
                span_ids = [
                    item["span_id"]
                    for item in json.loads(str(kwargs["input"][0]["text"]).split("\n", 1)[1])["spans"]  # type: ignore[index]
                ]
                parsed = {
                    "schema_version": 1,
                    "candidates": [],
                    "ignored_span_ids": span_ids,
                    "warnings": [],
                }
                from types import SimpleNamespace

                return SimpleNamespace(
                    parsed=parsed,
                    text="{}",
                    provider="fixture",
                    model="fixture",
                    agent_id="fixture",
                    usage=None,
                )

        llm = CaptureLlm()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Synthetic shadow note", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            digest = sha256(note.read_bytes()).hexdigest()
            config = NexusConfig.from_mapping(
                {
                    "inbox_path": str(inbox),
                    "data_path": str(root / "data"),
                    "source_stable_seconds": 1,
                    "ingest_pipeline_v2": False,
                }
            )
            shadow_inbox_source(
                config,
                llm,
                relative_path="note.md",
                confirmed_sha256=digest,
            )
            self.assertEqual([90], llm.timeouts)
            self.assertFalse((root / "data" / "ingest").exists())

    def test_flag_on_shadow_uses_60_second_target_without_vault_writes(self) -> None:
        class CaptureLlm:
            def __init__(self) -> None:
                self.timeouts: list[float] = []

            def complete_structured(self, **kwargs: object) -> object:
                self.timeouts.append(float(kwargs["timeout"]))  # type: ignore[arg-type]
                span_ids = [
                    item["span_id"]
                    for item in json.loads(str(kwargs["input"][0]["text"]).split("\n", 1)[1])["spans"]  # type: ignore[index]
                ]
                parsed = {
                    "schema_version": 1,
                    "candidates": [],
                    "ignored_span_ids": span_ids,
                    "warnings": [],
                }
                from types import SimpleNamespace

                return SimpleNamespace(
                    parsed=parsed,
                    text="{}",
                    provider="fixture",
                    model="fixture",
                    agent_id="fixture",
                    usage=None,
                )

        llm = CaptureLlm()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            vault = root / "vault"
            inbox.mkdir()
            vault.mkdir()
            note = inbox / "note.md"
            note.write_text("Synthetic v2 shadow note", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            digest = sha256(note.read_bytes()).hexdigest()
            context = FakeContext(
                {
                    "vault_path": str(vault),
                    "inbox_path": str(inbox),
                    "data_path": str(root / "data"),
                    "source_stable_seconds": 1,
                    "ingest_pipeline_v2": True,
                    "auto_publish_enabled": False,
                },
                llm=llm,
            )
            arg_parser = __import__("argparse").ArgumentParser()
            configure_parser(arg_parser, lambda args: run_command(args, context))
            args = arg_parser.parse_args(
                ["ingest", "--shadow", "--source", "note.md", "--confirm-sha", digest, "--json"]
            )
            stream = io.StringIO()
            import contextlib

            with contextlib.redirect_stdout(stream):
                code = args.func(args)
            payload = json.loads(stream.getvalue())
            self.assertEqual(0, code)
            self.assertEqual([60.0], llm.timeouts)
            self.assertFalse(payload["vault_written"])
            self.assertFalse(payload["candidates_published"])
            self.assertFalse(list(vault.rglob("mem_*.md")))
            self.assertTrue((root / "data" / "ingest" / "v2" / "checkpoints").is_dir())

    def test_timeout_regression_four_conversations_complete_or_failed_segment(self) -> None:
        delays: list[float] = []

        class Flaky:
            def __init__(self, *, succeed_on: int) -> None:
                self.calls = 0
                self.succeed_on = succeed_on

            def __call__(self, segment: object) -> ExtractionResult:
                self.calls += 1
                if self.calls < self.succeed_on:
                    raise ExtractionError(
                        "structured extraction failed after 1 bounded attempt(s)",
                        failure_class="timeout",
                    )
                return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outcomes: list[str] = []
            for index in range(4):
                source = conversation(
                    (message("u1", "user", f"timeout-{index}"),),
                    external_id=f"timeout-conv-{index}",
                )
                succeed_on = 2 if index < 3 else 99
                report = self._run(
                    root / f"case-{index}",
                    source,
                    Flaky(succeed_on=succeed_on),
                    sleeper=delays.append,
                )
                outcomes.append(report.final_status)
                self.assertIn(report.final_status, {"completed", FAILED_SEGMENT})
                self.assertNotEqual("hang", report.final_status)
                if report.final_status == FAILED_SEGMENT:
                    self.assertEqual("timeout", report.error_class)
                    self.assertIn("timeout", str(report.why))
                    log = ingest_log_path(root / f"case-{index}" / "data").read_text(encoding="utf-8")
                    self.assertIn("timeout", log)
                    self.assertIn(FAILED_SEGMENT, log)
            self.assertEqual(3, outcomes.count("completed"))
            self.assertEqual(1, outcomes.count(FAILED_SEGMENT))
            self.assertTrue(delays)

    def test_sigkill_resume_keeps_checkpoint(self) -> None:
        source = conversation(
            (
                message("u1", "user", "aaaa"),
                message("a1", "assistant", "bbbb"),
                message("u2", "user", "cccc"),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            data = root / "data"
            vault.mkdir()
            data.mkdir()
            sentinel = root / "started"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["NEXUS_VAULT"] = str(vault)
            env["NEXUS_DATA"] = str(data)
            env["NEXUS_SENTINEL"] = str(sentinel)
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "\n".join(
                        [
                            "import os, time",
                            "from pathlib import Path",
                            "from nexus.config import NexusConfig",
                            "from nexus.contracts import MemoryType",
                            "from nexus.ingest_v2 import run_conversation",
                            "from tests.test_ingest_v2 import conversation, message, result_for",
                            "source = conversation((message('u1','user','aaaa'), message('a1','assistant','bbbb'), message('u2','user','cccc')))",
                            "class Extractor:",
                            "    def __init__(self):",
                            "        self.calls = 0",
                            "    def __call__(self, segment):",
                            "        self.calls += 1",
                            "        Path(os.environ['NEXUS_SENTINEL']).write_text(str(self.calls), encoding='utf-8')",
                            "        if self.calls == 2:",
                            "            time.sleep(30)",
                            "        return result_for(segment, 'Kullanıcı kısa yanıtları tercih ediyor.')",
                            "run_conversation(NexusConfig.from_mapping({'vault_path': os.environ['NEXUS_VAULT'], 'inbox_path': '/tmp', 'data_path': os.environ['NEXUS_DATA'], 'ingest_pipeline_v2': True}), source, Extractor(), canonical_memory_type=MemoryType.PREFERENCE, write_canonical=True, target_chars=4)",
                        ]
                    ),
                ],
                env=env,
            )
            deadline = time.time() + 10
            while time.time() < deadline and not sentinel.exists():
                time.sleep(0.05)
            self.assertTrue(sentinel.exists())
            while time.time() < deadline and sentinel.read_text(encoding="utf-8").strip() != "2":
                time.sleep(0.05)
            os.kill(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
            checkpoint_dir = data / "ingest" / "v2" / "checkpoints"
            files = list(checkpoint_dir.glob("*.json"))
            self.assertEqual(1, len(files))
            payload = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertTrue(payload.get("complete"))
            statuses = [item["status"] for item in payload["segments"].values()]
            self.assertIn("completed", statuses)
            self.assertIn("incomplete", statuses)

            class Resume:
                def __init__(self) -> None:
                    self.calls = 0

                def __call__(self, segment: object) -> ExtractionResult:
                    self.calls += 1
                    statements = {
                        1: "Kullanıcı kısa yanıtları tercih ediyor.",
                        2: "Kullanıcı sade kahveyi tercih ediyor.",
                        3: "Kullanıcı erken saati tercih ediyor.",
                    }
                    return result_for(segment, statements[segment.index])  # type: ignore[attr-defined]

            extractor = Resume()
            report = run_conversation(
                NexusConfig.from_mapping(
                    {
                        "vault_path": str(vault),
                        "inbox_path": str(root / "inbox"),
                        "data_path": str(data),
                        "ingest_pipeline_v2": True,
                    }
                ),
                source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
                target_chars=4,
            )
            self.assertEqual("completed", report.final_status)
            self.assertEqual(2, extractor.calls)
            self.assertEqual(3, len(current_memories(load_ledger(data))))

    def test_idempotent_second_run_accepted_zero(self) -> None:
        source = conversation((message("u1", "user", "tekrar"),))

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._run(root, source, extractor)
            second = self._run(root, source, extractor)
            self.assertEqual(1, first.accepted)
            self.assertEqual(0, second.accepted)
            self.assertEqual(0, second.to_dict()["duplicates_created"])
            self.assertEqual("already_processed", second.final_status)

    def test_similar_claims_merge_to_one_memory(self) -> None:
        source = conversation(
            (
                message("u1", "user", "aaaa"),
                message("a1", "assistant", "bbbb"),
            )
        )

        class Extractor:
            def __call__(self, segment: object) -> ExtractionResult:
                if segment.index == 1:  # type: ignore[attr-defined]
                    return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")
                return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor!")

        with tempfile.TemporaryDirectory() as directory:
            report = self._run(Path(directory), source, Extractor(), target_chars=4)
            self.assertEqual(1, report.memories_created)
            self.assertGreaterEqual(report.duplicate_prevented_count, 1)

    def test_supersede_chain_collapses_to_one_current(self) -> None:
        statements = [
            "Kullanıcı kısa yanıtları tercih ediyor.",
            "Kullanıcı sade kahveyi tercih ediyor.",
            "Kullanıcı erken saati tercih ediyor.",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            prior: str | None = None
            for index, statement in enumerate(statements):
                source = conversation(
                    (message("u1", "user", f"pref-{index}"),),
                    external_id=f"pref-{index}",
                )

                def extractor(segment: object, text: str = statement, marker: str | None = prior) -> ExtractionResult:
                    return result_for(segment, text, supersedes=() if marker is None else (marker,))

                self._run(root, source, extractor)
                prior = current_memories(load_ledger(data))[0]["id"]
            rows = load_ledger(data)
            current = current_memories(rows)
            self.assertEqual(1, len(current))
            historical = [row for row in rows if row["status"] == "superseded"]
            self.assertEqual(2, len(historical))
            self.assertTrue(all(row["superseded_by"] == current[0]["id"] for row in historical))
            self.assertEqual(2, len(current[0]["supersedes"]))

    def test_namespace_writes_stay_under_nexus(self) -> None:
        source = conversation((message("u1", "user", "klasor"),))

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root, source, extractor)
            files = [path.relative_to(root / "vault") for path in (root / "vault").rglob("*.md") if path.is_file()]
            self.assertTrue(files)
            self.assertTrue(all(path.parts[0] == "Nexus" for path in files))

    def test_pause_blocks_vault_writes(self) -> None:
        source = conversation((message("u1", "user", "dur"),))

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = config_for(root)
            pause_ingest(config)
            report = run_conversation(
                config,
                source,
                extractor,
                canonical_memory_type=MemoryType.PREFERENCE,
                write_canonical=True,
            )
            self.assertEqual("completed", report.final_status)
            self.assertFalse(report.vault_written)
            self.assertFalse(list((root / "vault").rglob("mem_*.md")))
            self.assertTrue((root / "data" / "ingest" / "v2" / "PAUSED").is_file())

    def test_finance_and_low_confidence_never_auto_write(self) -> None:
        source = conversation((message("u1", "user", "risk"),))

        def finance(segment: object) -> ExtractionResult:
            from nexus.extraction.schema import CandidateKind

            span = segment.messages[0].message_id  # type: ignore[attr-defined]
            return ExtractionResult(
                candidates=(
                    ExtractionCandidate(
                        kind=CandidateKind.MEMORY,
                        statement="Kredi kartı borcum 5000 lira.",
                        entity_mentions=(),
                        temporal_expression=None,
                        source_span_ids=(span,),
                        confidence=0.99,
                        ambiguity_flags=(),
                        possible_supersedes=(),
                    ),
                ),
                ignored_span_ids=(),
                warnings=(),
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._run(root, source, finance)
            self.assertEqual(0, report.memories_created)
            self.assertFalse(list((root / "vault").rglob("mem_*.md")))
            queue = review_queue_path(root / "data").read_text(encoding="utf-8")
            self.assertIn("review_gate", queue)

    def test_content_hash_mismatch_goes_to_review(self) -> None:
        first = conversation((message("u1", "user", "alpha"),))
        second = conversation((message("u1", "user", "omega"),))

        def extractor(segment: object) -> ExtractionResult:
            return result_for(segment, "Kullanıcı kısa yanıtları tercih ediyor.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._run(root, first, extractor)
            later = self._run(root, second, extractor)
            self.assertEqual("review", next(iter(later.segment_statuses.values())))
            self.assertEqual("content_hash_mismatch", later.why)
            queue = review_queue_path(root / "data").read_text(encoding="utf-8")
            self.assertIn("content_hash_mismatch", queue)

    def test_status_cli_explains_failure(self) -> None:
        source = conversation((message("u1", "user", "neden"),))

        def extractor(segment: object) -> ExtractionResult:
            raise ExtractionError(
                "structured extraction failed after 1 bounded attempt(s)",
                failure_class="timeout",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = self._run(root, source, extractor)
            payload = status_payload(config_for(root, enabled=True), report.ingest_id)
            self.assertIn("timeout", str(payload.get("why")))
            self.assertFalse(payload["extraction_called"])
            rows = [
                json.loads(line)
                for line in ingest_log_path(root / "data").read_text(encoding="utf-8").splitlines()
                if line
            ]
            failed = next(row for row in rows if row.get("final_status") == FAILED_SEGMENT)
            self.assertIsInstance(failed.get("token_estimate"), int)
            self.assertGreaterEqual(failed["token_estimate"], 1)

    def test_pause_cli_stops_writes_without_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = FakeContext(
                {
                    "vault_path": str(root / "vault"),
                    "data_path": str(root / "data"),
                    "inbox_path": str(root / "inbox"),
                    "ingest_pipeline_v2": True,
                }
            )
            (root / "data").mkdir()
            arg_parser = __import__("argparse").ArgumentParser()
            configure_parser(arg_parser, lambda args: run_command(args, context))
            args = arg_parser.parse_args(["ingest", "pause", "--json"])
            stream = io.StringIO()
            import contextlib

            with contextlib.redirect_stdout(stream):
                code = args.func(args)
            payload = json.loads(stream.getvalue())
            self.assertEqual(0, code)
            self.assertTrue(payload["paused"])
            self.assertFalse(payload["vault_writes"])
            self.assertTrue((root / "data" / "ingest" / "v2" / "PAUSED").is_file())

    def test_long_unit_budget_is_logged_and_not_silent(self) -> None:
        source = conversation((message("u1", "user", "abcdefghijKLMNO"),))

        class Capture:
            def __init__(self) -> None:
                self.timeouts: list[float] = []
                self.uses: list[dict] = []

            def complete_structured(self, **kwargs: object) -> object:
                self.timeouts.append(float(kwargs["timeout"]))  # type: ignore[arg-type]
                span_ids = [
                    item["span_id"]
                    for item in json.loads(str(kwargs["input"][0]["text"]).split("\n", 1)[1])["spans"]  # type: ignore[index]
                ]
                from types import SimpleNamespace

                return SimpleNamespace(
                    parsed={
                        "schema_version": 1,
                        "candidates": [],
                        "ignored_span_ids": span_ids,
                        "warnings": [],
                    },
                    text="{}",
                    provider="fixture",
                    model="fixture",
                    agent_id="fixture",
                    usage=None,
                )

        llm = Capture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extractor = service_extractor(
                llm,
                long_unit_budget=LONG_UNIT_DEFAULT_SECONDS,
                long_unit_log=llm.uses.append,
            )
            run_conversation(
                config_for(root),
                source,
                extractor,
                write_canonical=False,
                target_chars=5,
            )
            self.assertTrue(llm.timeouts)
            self.assertTrue(all(value == float(LONG_UNIT_DEFAULT_SECONDS) for value in llm.timeouts))
            self.assertEqual(len(llm.timeouts), len(llm.uses))
            self.assertTrue(all(item["human_triggered"] for item in llm.uses))


if __name__ == "__main__":
    unittest.main()
