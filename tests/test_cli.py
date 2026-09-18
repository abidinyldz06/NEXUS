from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from nexus.cli import configure_parser, run_command
from nexus.contracts import SourceRef
from nexus.eval import frozen_fixture_path
from nexus.ids import IdPrefix, new_id
from nexus.review import ReviewStore, create_review_item


class FakeContext:
    def __init__(self, values: dict[str, object] | None = None, llm: object | None = None) -> None:
        self.values = values or {}
        self.llm = llm

    def get_config(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)


def parser_for(ctx: FakeContext) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    configure_parser(parser, lambda args: run_command(args, ctx))
    return parser


class CliTests(unittest.TestCase):
    def test_status_is_read_only_and_reports_missing_vault(self) -> None:
        parser = parser_for(FakeContext())
        args = parser.parse_args(["status", "--json"])
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        payload = json.loads(stream.getvalue())
        self.assertEqual(0, result)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["write_enabled"])

    def test_config_validate_succeeds_for_existing_vault(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parser = parser_for(FakeContext({"vault_path": directory}))
            args = parser.parse_args(["config", "validate", "--json"])
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

        self.assertEqual(0, result)
        self.assertTrue(json.loads(stream.getvalue())["ok"])
        self.assertTrue(json.loads(stream.getvalue())["write_enabled"])
        self.assertEqual(
            "explicit-confirmed-operations",
            json.loads(stream.getvalue())["write_scope"],
        )

    def test_ingest_requires_explicit_mode(self) -> None:
        parser = parser_for(FakeContext())
        args = parser.parse_args(["ingest", "--json"])
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        self.assertEqual(2, result)
        self.assertIn("requires exactly one", stream.getvalue())

    def test_ingest_dry_run_parses_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Sentetik kalıcı tercih", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            context = FakeContext(
                {
                    "inbox_path": str(inbox),
                    "data_path": str(root / "private"),
                    "source_stable_seconds": 1,
                }
            )
            parser = parser_for(context)
            args = parser.parse_args(["ingest", "--dry-run", "--json"])
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(0, result)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["writes_performed"])
            self.assertEqual(1, payload["summary"]["messages"])
            self.assertFalse((root / "private").exists())

    def test_ingest_shadow_requires_exact_source_and_reports_aggregates_only(self) -> None:
        class ShadowLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_ids = [item["span_id"] for item in envelope["spans"]]
                parsed = {
                    "schema_version": 1,
                    "candidates": [
                        {
                            "kind": "memory",
                            "statement": "Synthetic durable preference",
                            "entity_mentions": [],
                            "temporal_expression": None,
                            "source_span_ids": span_ids,
                            "confidence": 0.95,
                            "ambiguity_flags": [],
                            "possible_supersedes": [],
                        }
                    ],
                    "ignored_span_ids": [],
                    "warnings": [],
                }
                return SimpleNamespace(
                    parsed=parsed,
                    text=json.dumps(parsed),
                    provider="fixture-provider",
                    model="fixture-model",
                    agent_id="fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "private-note.md"
            private_text = "DO_NOT_PRINT synthetic durable preference"
            note.write_text(private_text, encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            digest = sha256(note.read_bytes()).hexdigest()
            context = FakeContext(
                {
                    "inbox_path": str(inbox),
                    "data_path": str(root / "private"),
                    "source_stable_seconds": 1,
                },
                llm=ShadowLlm(),
            )
            parser = parser_for(context)
            args = parser.parse_args(
                [
                    "ingest",
                    "--shadow",
                    "--source",
                    note.name,
                    "--confirm-sha",
                    digest,
                    "--json",
                ]
            )
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            output = stream.getvalue()
            payload = json.loads(output)
            self.assertEqual(0, result)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["writes_performed"])
            self.assertFalse(payload["candidates_published"])
            self.assertEqual(20, payload["extraction"]["segment_limit"])
            self.assertEqual({"memory": 1}, payload["extraction"]["candidate_kinds"])
            self.assertEqual(["fixture-model"], payload["audit"]["models"])
            self.assertNotIn(private_text, output)
            self.assertNotIn("Synthetic durable preference", output)
            self.assertFalse((root / "private").exists())

    def test_ingest_shadow_rejects_wrong_confirmation_before_model_call(self) -> None:
        class NoCallLlm:
            def complete_structured(self, **kwargs):
                raise AssertionError("model must not be called for a mismatched SHA")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Synthetic", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            parser = parser_for(
                FakeContext(
                    {"inbox_path": str(inbox), "source_stable_seconds": 1},
                    llm=NoCallLlm(),
                )
            )
            args = parser.parse_args(
                [
                    "ingest",
                    "--shadow",
                    "--source",
                    note.name,
                    "--confirm-sha",
                    "0" * 64,
                    "--json",
                ]
            )
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(2, result)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["writes_performed"])
            self.assertIn("does not match", payload["errors"][0])

    def test_ingest_stage_writes_private_review_state_without_vault_publication(self) -> None:
        class StageLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_ids = [item["span_id"] for item in envelope["spans"]]
                parsed = {
                    "schema_version": 1,
                    "candidates": [
                        {
                            "kind": "memory",
                            "statement": "Synthetic durable preference",
                            "entity_mentions": [],
                            "temporal_expression": None,
                            "source_span_ids": span_ids,
                            "confidence": 0.95,
                            "ambiguity_flags": [],
                            "possible_supersedes": [],
                        }
                    ],
                    "ignored_span_ids": [],
                    "warnings": [],
                }
                return SimpleNamespace(
                    parsed=parsed,
                    provider="fixture-provider",
                    model="fixture-model",
                    agent_id="fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Kısa yanıtları tercih ederim.", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            digest = sha256(note.read_bytes()).hexdigest()
            vault = root / "vault-must-not-exist"
            context = FakeContext(
                {
                    "vault_path": str(vault),
                    "inbox_path": str(inbox),
                    "data_path": str(root / "private"),
                    "source_stable_seconds": 1,
                },
                llm=StageLlm(),
            )
            parser = parser_for(context)
            args = parser.parse_args(
                [
                    "ingest",
                    "--stage",
                    "--source",
                    note.name,
                    "--confirm-sha",
                    digest,
                    "--json",
                ]
            )
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(0, result)
            self.assertTrue(payload["writes_performed"])
            self.assertFalse(payload["vault_writes"])
            self.assertFalse(payload["candidates_published"])
            self.assertEqual(1, payload["review"]["created"])
            self.assertEqual(1, len(ReviewStore(root / "private").list()))
            self.assertNotIn("Kısa yanıtları tercih ederim", stream.getvalue())
            self.assertNotIn("Synthetic durable preference", stream.getvalue())
            self.assertFalse(vault.exists())

    def test_ingest_shadow_requires_conversation_for_multi_conversation_source(self) -> None:
        class NoCallLlm:
            def complete_structured(self, **kwargs):
                raise AssertionError("model must not be called before conversation selection")

        def conversation(identifier: str) -> dict[str, object]:
            message_id = f"message-{identifier}"
            return {
                "id": identifier,
                "current_node": message_id,
                "mapping": {
                    message_id: {
                        "id": message_id,
                        "parent": None,
                        "message": {
                            "id": message_id,
                            "author": {"role": "user"},
                            "content": {"parts": [f"Synthetic {identifier}"]},
                        },
                    }
                },
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            export = inbox / "conversations.json"
            export.write_text(
                json.dumps([conversation("conversation-1"), conversation("conversation-2")]),
                encoding="utf-8",
            )
            old = time.time() - 60
            os.utime(export, (old, old))
            digest = sha256(export.read_bytes()).hexdigest()
            parser = parser_for(
                FakeContext(
                    {"inbox_path": str(inbox), "source_stable_seconds": 1},
                    llm=NoCallLlm(),
                )
            )
            args = parser.parse_args(
                [
                    "ingest",
                    "--shadow",
                    "--source",
                    export.name,
                    "--confirm-sha",
                    digest,
                    "--json",
                ]
            )
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(2, result)
            self.assertIn("require --conversation", payload["errors"][0])

            class SelectedLlm:
                def complete_structured(self, **kwargs):
                    envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                    span_ids = [item["span_id"] for item in envelope["spans"]]
                    parsed = {
                        "schema_version": 1,
                        "candidates": [],
                        "ignored_span_ids": span_ids,
                        "warnings": [],
                    }
                    return SimpleNamespace(
                        parsed=parsed,
                        text=json.dumps(parsed),
                        provider="fixture-provider",
                        model="fixture-model",
                        agent_id="fixture-agent",
                        usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                    )

            selected_parser = parser_for(
                FakeContext(
                    {"inbox_path": str(inbox), "source_stable_seconds": 1},
                    llm=SelectedLlm(),
                )
            )
            selected_args = selected_parser.parse_args(
                [
                    "ingest",
                    "--shadow",
                    "--source",
                    export.name,
                    "--confirm-sha",
                    digest,
                    "--conversation",
                    "conversation-2",
                    "--json",
                ]
            )
            selected_stream = io.StringIO()
            with contextlib.redirect_stdout(selected_stream):
                selected_result = selected_args.func(selected_args)

            selected_payload = json.loads(selected_stream.getvalue())
            self.assertEqual(0, selected_result)
            self.assertEqual(1, selected_payload["source"]["conversations"])
            self.assertEqual(1, selected_payload["audit"]["successful_calls"])

    def test_ingest_shadow_rejects_segment_limit_before_model_call(self) -> None:
        class NoCallLlm:
            def complete_structured(self, **kwargs):
                raise AssertionError("model must not be called for an invalid segment limit")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "inbox"
            inbox.mkdir()
            note = inbox / "note.md"
            note.write_text("Synthetic", encoding="utf-8")
            old = time.time() - 60
            os.utime(note, (old, old))
            digest = sha256(note.read_bytes()).hexdigest()
            parser = parser_for(
                FakeContext(
                    {"inbox_path": str(inbox), "source_stable_seconds": 1},
                    llm=NoCallLlm(),
                )
            )
            args = parser.parse_args(
                [
                    "ingest",
                    "--shadow",
                    "--source",
                    note.name,
                    "--confirm-sha",
                    digest,
                    "--max-segments",
                    "0",
                    "--json",
                ]
            )
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(2, result)
            self.assertIn("between 1 and 100", payload["errors"][0])

    def test_retention_requires_dry_run_and_reports_aggregate_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "private"
            raw_path = data_path / "raw" / "aa"
            raw_path.mkdir(parents=True)
            old = raw_path / "old.json"
            old.write_text("synthetic", encoding="utf-8")
            os.utime(old, (1, 1))
            parser = parser_for(
                FakeContext({"data_path": str(data_path), "raw_retention_days": 1})
            )

            missing_gate = parser.parse_args(["retention", "--json"])
            missing_stream = io.StringIO()
            with contextlib.redirect_stdout(missing_stream):
                missing_result = missing_gate.func(missing_gate)

            args = parser.parse_args(["retention", "--dry-run", "--json"])
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(2, missing_result)
            self.assertIn("only supports", missing_stream.getvalue())
            self.assertEqual(0, result)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["writes_performed"])
            self.assertEqual(1, payload["raw"]["expired_files"])
            self.assertTrue(old.exists())

    def test_forget_requires_explicit_mode_and_exact_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            target_id = new_id(IdPrefix.MEMORY)
            parser = parser_for(
                FakeContext(
                    {
                        "vault_path": str(vault),
                        "data_path": str(root / "private"),
                    }
                )
            )

            dry_run = parser.parse_args(["forget", target_id, "--dry-run", "--json"])
            dry_stream = io.StringIO()
            with contextlib.redirect_stdout(dry_stream):
                dry_result = dry_run.func(dry_run)

            apply = parser.parse_args(
                [
                    "forget",
                    target_id,
                    "--apply",
                    "--confirm",
                    new_id(IdPrefix.MEMORY),
                    "--json",
                ]
            )
            apply_stream = io.StringIO()
            with contextlib.redirect_stdout(apply_stream):
                apply_result = apply.func(apply)

            self.assertEqual(2, dry_result)
            self.assertIn("not found", dry_stream.getvalue())
            self.assertEqual(2, apply_result)
            self.assertIn("exactly match", apply_stream.getvalue())
            self.assertFalse((root / "private").exists())

    def test_permission_audit_reports_aggregate_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "private"
            data_path.mkdir()
            os.chmod(data_path, 0o700)
            private_file = data_path / "do-not-print-this-name.json"
            private_file.write_text("do-not-print-this-content", encoding="utf-8")
            os.chmod(private_file, 0o600)
            parser = parser_for(
                FakeContext(
                    {"data_path": str(data_path), "inbox_path": str(root / "missing-inbox")}
                )
            )
            args = parser.parse_args(["audit", "permissions", "--json"])
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            output = stream.getvalue()
            payload = json.loads(output)
            self.assertEqual(0, result)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["writes_performed"])
            self.assertNotIn("do-not-print", output)

    def test_restore_drill_requires_synthetic_gate_and_ignores_user_config(self) -> None:
        class NoConfigContext:
            def get_config(self, key: str, default: object = None) -> object:
                raise AssertionError(f"production config must not be read: {key}")

        parser = parser_for(NoConfigContext())
        missing_gate = parser.parse_args(["drill", "restore", "--json"])
        missing_stream = io.StringIO()
        with contextlib.redirect_stdout(missing_stream):
            missing_result = missing_gate.func(missing_gate)

        args = parser.parse_args(["drill", "restore", "--synthetic", "--json"])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        payload = json.loads(stream.getvalue())
        self.assertEqual(2, missing_result)
        self.assertIn("only supports", missing_stream.getvalue())
        self.assertEqual(0, result)
        self.assertTrue(payload["ok"])
        self.assertEqual("synthetic-temporary", payload["mode"])
        self.assertFalse(payload["production_paths_accessed"])
        self.assertFalse(payload["production_writes"])

    def test_git_rollback_drill_requires_synthetic_gate_and_ignores_config(self) -> None:
        class NoConfigContext:
            def get_config(self, key: str, default: object = None) -> object:
                raise AssertionError(f"production config must not be read: {key}")

        parser = parser_for(NoConfigContext())
        missing_gate = parser.parse_args(["drill", "git-rollback", "--json"])
        missing_stream = io.StringIO()
        with contextlib.redirect_stdout(missing_stream):
            missing_result = missing_gate.func(missing_gate)

        args = parser.parse_args(["drill", "git-rollback", "--synthetic", "--json"])
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        payload = json.loads(stream.getvalue())
        self.assertEqual(2, missing_result)
        self.assertIn("only supports", missing_stream.getvalue())
        self.assertEqual(0, result)
        self.assertTrue(payload["ok"])
        self.assertEqual(6, payload["files"])
        self.assertTrue(payload["metadata_external"])
        self.assertFalse(payload["production_paths_accessed"])
        self.assertFalse(payload["production_writes"])

    def test_eval_requires_explicit_shadow_gate(self) -> None:
        parser = parser_for(FakeContext())
        args = parser.parse_args(["eval", "--json"])
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        self.assertEqual(2, result)
        self.assertIn("eval --shadow", stream.getvalue())

    def test_eval_shadow_reports_metrics_without_publishing(self) -> None:
        fixture = json.loads(frozen_fixture_path().read_text(encoding="utf-8"))
        expected_by_case = {
            item["id"]: item["expected_kinds"] for item in fixture["cases"]
        }

        class FixtureLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_ids = [item["span_id"] for item in envelope["spans"]]
                candidates = [
                    {
                        "kind": kind,
                        "statement": f"Synthetic expected {kind}",
                        "entity_mentions": [],
                        "temporal_expression": None,
                        "source_span_ids": [span_ids[0]],
                        "confidence": 0.95,
                        "ambiguity_flags": [],
                        "possible_supersedes": [],
                    }
                    for kind in expected_by_case[envelope["conversation_id"]]
                ]
                ignored = span_ids[1:] if candidates else span_ids
                parsed = {
                    "schema_version": 1,
                    "candidates": candidates,
                    "ignored_span_ids": ignored,
                    "warnings": [],
                }
                return SimpleNamespace(
                    parsed=parsed,
                    text=json.dumps(parsed),
                    provider="fixture-provider",
                    model="fixture-model",
                    agent_id="fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        parser = parser_for(FakeContext(llm=FixtureLlm()))
        args = parser.parse_args(["eval", "--shadow", "--json"])
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        payload = json.loads(stream.getvalue())
        self.assertEqual(0, result)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["writes_performed"])
        self.assertFalse(payload["candidates_published"])
        self.assertEqual(["fixture-model"], payload["report"]["models"])
        self.assertEqual(1.0, payload["report"]["metrics"]["expected_kind_precision"])
        self.assertEqual(1.0, payload["report"]["metrics"]["exact_case_match_rate"])

    def test_private_eval_requires_exact_sha_and_reports_aggregates_only(self) -> None:
        class PrivateFixtureLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_id = envelope["spans"][0]["span_id"]
                parsed = {
                    "schema_version": 1,
                    "candidates": [
                        {
                            "kind": "memory",
                            "statement": "Synthetic private expectation",
                            "entity_mentions": [],
                            "temporal_expression": None,
                            "source_span_ids": [span_id],
                            "confidence": 0.95,
                            "ambiguity_flags": [],
                            "possible_supersedes": [],
                        }
                    ],
                    "ignored_span_ids": [],
                    "warnings": [],
                }
                return SimpleNamespace(
                    parsed=parsed,
                    text=json.dumps(parsed),
                    provider="private-fixture-provider",
                    model="private-fixture-model",
                    agent_id="private-fixture-agent",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15),
                )

        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory)
            private_root = data_path / "eval/private"
            private_root.mkdir(parents=True)
            private_root.chmod(0o700)
            fixture = private_root / "golden-v1.json"
            secret_content = "PRIVATE_GOLDEN_CONTENT_MUST_NOT_APPEAR"
            fixture.write_text(
                json.dumps(
                    {
                        "fixture_version": 1,
                        "dataset": "private-golden",
                        "cases": [
                            {
                                "id": "private-case-1",
                                "messages": [
                                    {
                                        "id": "private-message-1",
                                        "role": "user",
                                        "content": secret_content,
                                    }
                                ],
                                "expected_kinds": ["memory"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            fixture.chmod(0o600)
            digest = sha256(fixture.read_bytes()).hexdigest()
            parser = parser_for(
                FakeContext(
                    {"data_path": str(data_path)},
                    llm=PrivateFixtureLlm(),
                )
            )

            missing_confirmation = parser.parse_args(
                ["eval", "--shadow", "--private-dataset", fixture.name, "--json"]
            )
            missing_stream = io.StringIO()
            with contextlib.redirect_stdout(missing_stream):
                missing_result = missing_confirmation.func(missing_confirmation)

            args = parser.parse_args(
                [
                    "eval",
                    "--shadow",
                    "--private-dataset",
                    fixture.name,
                    "--confirm-sha",
                    digest,
                    "--json",
                ]
            )
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(2, missing_result)
            self.assertIn("requires --confirm-sha", missing_stream.getvalue())
            self.assertEqual(0, result)
            self.assertTrue(payload["ok"])
            self.assertEqual("private", payload["dataset"])
            self.assertFalse(payload["writes_performed"])
            self.assertFalse(payload["candidates_published"])
            self.assertNotIn(secret_content, stream.getvalue())
            self.assertNotIn(fixture.name, stream.getvalue())
            self.assertEqual(1, payload["report"]["metrics"]["cases"])

    def test_review_cli_lists_and_approves_without_vault_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReviewStore(root)
            item = store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={"statement": "Kısa yanıt tercihi"},
                    reason_codes=("medium_confidence",),
                    source_refs=(
                        SourceRef(
                            source_id=new_id(IdPrefix.SOURCE),
                            conversation_id="conversation-1",
                            span_ids=("msg_1",),
                            span_sha256=sha256(b"msg_1").hexdigest(),
                        ),
                    ),
                )
            )
            parser = parser_for(FakeContext({"data_path": str(root)}))

            list_args = parser.parse_args(["review", "list", "--json"])
            list_stream = io.StringIO()
            with contextlib.redirect_stdout(list_stream):
                list_result = list_args.func(list_args)

            approve_args = parser.parse_args(
                ["review", "approve", item.id, "--reason", "Kaynak açık", "--json"]
            )
            approve_stream = io.StringIO()
            with contextlib.redirect_stdout(approve_stream):
                approve_result = approve_args.func(approve_args)

            listed = json.loads(list_stream.getvalue())
            approved = json.loads(approve_stream.getvalue())
            self.assertEqual(0, list_result)
            self.assertEqual([item.id], [value["id"] for value in listed["items"]])
            self.assertEqual(0, approve_result)
            self.assertEqual("approved", approved["item"]["status"])
            self.assertFalse(approved["vault_writes"])

    def test_review_cli_edit_requires_absolute_regular_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ReviewStore(root)
            item = store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={"statement": "Eski"},
                    reason_codes=("candidate_ambiguous",),
                    source_refs=(
                        SourceRef(
                            source_id=new_id(IdPrefix.SOURCE),
                            conversation_id="conversation-1",
                            span_ids=("msg_1",),
                            span_sha256=sha256(b"msg_1").hexdigest(),
                        ),
                    ),
                )
            )
            edited_path = root / "edited.json"
            edited_path.write_text('{"statement":"Yeni"}', encoding="utf-8")
            parser = parser_for(FakeContext({"data_path": str(root)}))
            args = parser.parse_args(
                [
                    "review",
                    "edit",
                    item.id,
                    "--candidate-file",
                    str(edited_path),
                    "--json",
                ]
            )
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                result = args.func(args)

            payload = json.loads(stream.getvalue())
            self.assertEqual(0, result)
            self.assertEqual("edited", payload["item"]["status"])
            self.assertEqual("Yeni", payload["item"]["candidate"]["statement"])
            self.assertFalse(payload["vault_writes"])

    def test_review_publish_requires_dry_run_and_exact_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            store = ReviewStore(root / "private")
            item = store.enqueue(
                create_review_item(
                    candidate_kind="memory",
                    candidate={
                        "statement": "CLI üzerinden onaylı sentetik hafıza",
                        "memory_type": "fact",
                        "confidence": 0.95,
                        "impact": "low",
                    },
                    reason_codes=("operator_review",),
                    source_refs=(
                        SourceRef(
                            source_id=new_id(IdPrefix.SOURCE),
                            conversation_id="conversation-publish",
                            span_ids=("msg_publish",),
                            span_sha256=sha256(b"msg_publish").hexdigest(),
                        ),
                    ),
                )
            )
            store.decide(item.id, action="approve")
            parser = parser_for(
                FakeContext(
                    {
                        "vault_path": str(vault),
                        "data_path": str(root / "private"),
                    }
                )
            )

            dry_args = parser.parse_args(
                ["review", "publish", item.id, "--dry-run", "--json"]
            )
            dry_stream = io.StringIO()
            with contextlib.redirect_stdout(dry_stream):
                dry_result = dry_args.func(dry_args)

            apply_args = parser.parse_args(
                [
                    "review",
                    "publish",
                    item.id,
                    "--apply",
                    "--confirm",
                    item.id,
                    "--json",
                ]
            )
            apply_stream = io.StringIO()
            with contextlib.redirect_stdout(apply_stream):
                apply_result = apply_args.func(apply_args)

            self.assertEqual(0, dry_result)
            self.assertFalse(json.loads(dry_stream.getvalue())["writes_performed"])
            self.assertEqual(0, apply_result)
            payload = json.loads(apply_stream.getvalue())
            self.assertTrue(payload["vault_writes"])
            self.assertTrue(payload["record_id"].startswith("mem_"))

    def test_rebuild_and_search_cli_use_only_derived_index(self) -> None:
        from nexus.contracts import Impact, Memory, MemoryType, ReviewStatus
        from nexus.vault import VaultRepository

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            data = root / "private"
            record = Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.PREFERENCE,
                summary="Kullanıcı kısa ve sade Türkçe yanıtları tercih ediyor",
                source_refs=(
                    SourceRef(
                        source_id=new_id(IdPrefix.SOURCE),
                        conversation_id="conversation-index",
                        span_ids=("msg_1",),
                        span_sha256=sha256(b"msg_1").hexdigest(),
                    ),
                ),
                confidence=0.95,
                impact=Impact.LOW,
                review_status=ReviewStatus.APPROVED,
            )
            VaultRepository(vault).commit_records((record,), run_id=new_id(IdPrefix.RUN))
            parser = parser_for(
                FakeContext({"vault_path": str(vault), "data_path": str(data)})
            )

            rebuild_args = parser.parse_args(["rebuild", "--json"])
            rebuild_stream = io.StringIO()
            with contextlib.redirect_stdout(rebuild_stream):
                rebuild_result = rebuild_args.func(rebuild_args)

            search_args = parser.parse_args(["search", "kısa Türkçe", "--json"])
            search_stream = io.StringIO()
            with contextlib.redirect_stdout(search_stream):
                search_result = search_args.func(search_args)

            rebuilt = json.loads(rebuild_stream.getvalue())
            searched = json.loads(search_stream.getvalue())
            self.assertEqual(0, rebuild_result)
            self.assertEqual(1, rebuilt["records"])
            self.assertFalse(rebuilt["vault_writes"])
            self.assertEqual(0, search_result)
            self.assertEqual([record.id], [item["id"] for item in searched["items"]])
            self.assertFalse(searched["vault_writes"])

    def test_reminders_requires_local_gate_and_empty_queue_is_silent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            data = root / "private"
            from nexus.index import rebuild_index

            rebuild_index(vault, data / "nexus.db")
            parser = parser_for(
                FakeContext({"vault_path": str(vault), "data_path": str(data)})
            )

            missing_gate = parser.parse_args(["reminders"])
            missing_stream = io.StringIO()
            with contextlib.redirect_stdout(missing_stream):
                missing_result = missing_gate.func(missing_gate)

            emit = parser.parse_args(["reminders", "--emit-local"])
            emit_stream = io.StringIO()
            with contextlib.redirect_stdout(emit_stream):
                emit_result = emit.func(emit)

            self.assertEqual(2, missing_result)
            self.assertIn("--emit-local", missing_stream.getvalue())
            self.assertEqual(0, emit_result)
            self.assertEqual("", emit_stream.getvalue())


if __name__ == "__main__":
    unittest.main()
