from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from nexus.cli import configure_parser, run_command


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

    def test_ingest_requires_explicit_dry_run(self) -> None:
        parser = parser_for(FakeContext())
        args = parser.parse_args(["ingest", "--json"])
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        self.assertEqual(2, result)
        self.assertIn("only supports", stream.getvalue())

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

    def test_eval_requires_explicit_shadow_gate(self) -> None:
        parser = parser_for(FakeContext())
        args = parser.parse_args(["eval", "--json"])
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            result = args.func(args)

        self.assertEqual(2, result)
        self.assertIn("eval --shadow", stream.getvalue())

    def test_eval_shadow_reports_metrics_without_publishing(self) -> None:
        class FixtureLlm:
            def complete_structured(self, **kwargs):
                envelope = json.loads(kwargs["input"][0]["text"].split("\n", 1)[1])
                span_ids = [item["span_id"] for item in envelope["spans"]]
                if envelope["conversation_id"] == "prompt-injection-data":
                    candidates = []
                    ignored = span_ids
                else:
                    candidates = [
                        {
                            "kind": "memory",
                            "statement": "Kullanıcı kısa yanıtları tercih ediyor.",
                            "entity_mentions": [],
                            "temporal_expression": None,
                            "source_span_ids": [span_ids[0]],
                            "confidence": 0.95,
                            "ambiguity_flags": [],
                            "possible_supersedes": [],
                        }
                    ]
                    ignored = span_ids[1:]
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


if __name__ == "__main__":
    unittest.main()
