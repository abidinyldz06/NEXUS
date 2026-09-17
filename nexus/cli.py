"""NEXUS CLI with explicit shadow and private-review safety boundaries."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from typing import Any

from . import __version__
from .config import from_plugin_context
from .errors import ConfigurationError, NexusError, NexusIndexError
from .eval import evaluate_with_llm_report, frozen_fixture_path
from .index import rebuild_index, search_index
from .ingest import plan_inbox
from .pulse import emit_due_reminders
from .retention import plan_retention
from .review.commands import configure_review_parser, run_review_command


def configure_parser(parser: ArgumentParser, handler: Callable[[Namespace], int]) -> None:
    subcommands = parser.add_subparsers(dest="nexus_command")

    status = subcommands.add_parser("status", help="Show read-only NEXUS readiness")
    status.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    config = subcommands.add_parser("config", help="Inspect NEXUS configuration")
    config_subcommands = config.add_subparsers(dest="config_command")
    validate = config_subcommands.add_parser("validate", help="Validate paths without writing")
    validate.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    ingest = subcommands.add_parser("ingest", help="Inspect Inbox sources without writing")
    ingest.add_argument(
        "--dry-run",
        action="store_true",
        help="Required safety gate; parse and report without archiving or publishing",
    )
    ingest.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    eval_command = subcommands.add_parser(
        "eval", help="Run the packaged frozen holdout without publishing"
    )
    eval_command.add_argument(
        "--shadow",
        action="store_true",
        help="Required safety gate; call the model but do not persist candidates",
    )
    eval_command.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    review = subcommands.add_parser(
        "review", help="Inspect or decide private review items without publishing"
    )
    configure_review_parser(review)

    rebuild = subcommands.add_parser(
        "rebuild", help="Rebuild the disposable SQLite index from the canonical Vault"
    )
    rebuild.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    search = subcommands.add_parser("search", help="Search the derived SQLite index")
    search.add_argument("query", help="Words to find; treated as literal terms")
    search.add_argument(
        "--kind",
        choices=("memory", "entity", "relation", "commitment", "source", "review"),
    )
    search.add_argument("--status")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    reminders = subcommands.add_parser(
        "reminders", help="Emit due commitments for local no-agent delivery"
    )
    reminders.add_argument(
        "--emit-local",
        action="store_true",
        help="Required safety gate; mark and print due reminders without sending externally",
    )

    retention = subcommands.add_parser(
        "retention", help="Inspect private-data expiry without deleting anything"
    )
    retention.add_argument(
        "--dry-run",
        action="store_true",
        help="Required safety gate; report aggregate expiry counts without writing",
    )
    retention.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    parser.set_defaults(func=handler)


def _status_payload(ctx: Any) -> dict[str, Any]:
    try:
        config = from_plugin_context(ctx)
    except ConfigurationError as exc:
        return {
            "ok": False,
            "version": __version__,
            "phase": "0-7-pulse-local",
            "write_enabled": False,
            "errors": [str(exc)],
        }

    errors = list(config.validate_existing_paths())
    return {
        "ok": not errors,
        "version": __version__,
        "phase": "0-7-pulse-local",
        "write_enabled": not errors and config.write_ready,
        "write_scope": "reminder-state-only" if not errors and config.write_ready else "none",
        "reminder_delivery": "local-only",
        "auto_publish_enabled": config.auto_publish_enabled,
        "sensitive_auto_publish": config.sensitive_auto_publish,
        "timezone": config.timezone,
        "paths": {
            "vault": str(config.vault_path) if config.vault_path else None,
            "inbox": str(config.inbox_path),
            "data": str(config.data_path),
            "index": str(config.index_path),
        },
        "errors": errors,
    }


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    state = "ready" if payload["ok"] else "not ready"
    print(f"NEXUS v{payload['version']} — Phase {payload['phase']} — {state}")
    if payload.get("write_enabled", False):
        print("Vault writes: explicit reminder-state updates only; canonical publish disabled")
    else:
        print("Vault writes: disabled; SQLite index is derived and rebuildable")
    for key, value in payload.get("paths", {}).items():
        print(f"{key}: {value or '<not configured>'}")
    for error in payload.get("errors", []):
        print(f"error: {error}")


def run_command(args: Namespace, ctx: Any) -> int:
    command = getattr(args, "nexus_command", None)
    if command == "status":
        payload = _status_payload(ctx)
        _print_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0
    if command == "config" and getattr(args, "config_command", None) == "validate":
        payload = _status_payload(ctx)
        _print_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "ingest":
        if not bool(getattr(args, "dry_run", False)):
            print("Phase 2 only supports: hermes nexus ingest --dry-run")
            return 2
        try:
            config = from_plugin_context(ctx)
            payload = plan_inbox(config).to_dict()
        except (ConfigurationError, OSError) as exc:
            payload = {
                "ok": False,
                "mode": "dry-run",
                "writes_performed": False,
                "errors": [str(exc)],
            }
        _print_ingest_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "eval":
        if not bool(getattr(args, "shadow", False)):
            print("Phase 3 only supports: hermes nexus eval --shadow")
            return 2
        payload = _shadow_eval_payload(ctx)
        _print_eval_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "review":
        try:
            config = from_plugin_context(ctx)
            result, payload = run_review_command(args, data_path=config.data_path)
        except ConfigurationError as exc:
            result, payload = 2, {
                "ok": False,
                "errors": [str(exc)],
                "vault_writes": False,
            }
        _print_review_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return result
    if command == "rebuild":
        payload = _rebuild_payload(ctx)
        _print_index_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "search":
        payload = _search_payload(args, ctx)
        _print_index_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "reminders":
        if not bool(getattr(args, "emit_local", False)):
            print("Phase 7 only supports: hermes nexus reminders --emit-local")
            return 2
        try:
            config = from_plugin_context(ctx)
            if config.vault_path is None:
                raise ConfigurationError("vault_path is not configured")
            output = emit_due_reminders(config.vault_path, config.index_path)
        except (NexusError, OSError) as exc:
            print(f"NEXUS reminder error: {exc}", file=sys.stderr)
            return 2
        if output:
            print(output)
        return 0
    if command == "retention":
        if not bool(getattr(args, "dry_run", False)):
            print("Phase 8 only supports: hermes nexus retention --dry-run")
            return 2
        try:
            payload = plan_retention(from_plugin_context(ctx)).to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "dry-run",
                "writes_performed": False,
                "errors": [str(exc)],
            }
        _print_retention_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    print(
        "Usage: hermes nexus "
        "{status|config validate|ingest --dry-run|eval --shadow|review ...|"
        "rebuild|search|reminders --emit-local|retention --dry-run}"
    )
    return 2


def _print_ingest_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    summary = payload.get("summary", {})
    print("NEXUS ingest dry-run — no writes performed")
    if isinstance(summary, dict):
        print(
            f"files: {summary.get('files', 0)}, conversations: "
            f"{summary.get('conversations', 0)}, messages: {summary.get('messages', 0)}, "
            f"rejected: {summary.get('rejected', 0)}"
        )
    for item in payload.get("rejected", []):
        if isinstance(item, dict):
            print(f"rejected: {item.get('relative_path')} — {item.get('reason')}")
    for error in payload.get("errors", []):
        print(f"error: {error}")


def _shadow_eval_payload(ctx: Any) -> dict[str, Any]:
    try:
        report = evaluate_with_llm_report(frozen_fixture_path(), ctx.llm)
    except Exception:
        return {
            "ok": False,
            "mode": "shadow",
            "writes_performed": False,
            "candidates_published": False,
            "errors": ["shadow evaluation failed without exposing provider details"],
        }
    return {
        "ok": report.accepted,
        "mode": "shadow",
        "writes_performed": False,
        "candidates_published": False,
        "report": report.to_dict(),
        "errors": [] if report.accepted else ["frozen holdout acceptance thresholds were not met"],
    }


def _print_eval_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print("NEXUS frozen evaluation — shadow mode; no candidates published")
    report = payload.get("report", {})
    if isinstance(report, dict):
        metrics = report.get("metrics", {})
        print(f"accepted: {report.get('accepted', False)}")
        print(f"providers: {', '.join(report.get('providers', [])) or '<unavailable>'}")
        print(f"models: {', '.join(report.get('models', [])) or '<unavailable>'}")
        if isinstance(metrics, dict):
            print(
                f"provenance: {metrics.get('provenance_rate', 0):.2f}, "
                f"expected-kind recall: {metrics.get('expected_kind_recall', 0):.2f}, "
                f"schema failures: {metrics.get('schema_failures', 0)}"
            )
    for error in payload.get("errors", []):
        print(f"error: {error}")


def _print_review_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False):
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    if "items" in payload:
        items = payload.get("items", [])
        print(f"NEXUS review queue — {len(items)} item(s); no Vault writes")
        for item in items:
            if isinstance(item, dict):
                print(
                    f"{item.get('id')}  {item.get('status')}  "
                    f"{item.get('candidate_kind')}  {','.join(item.get('reason_codes', []))}"
                )
        return
    item = payload.get("item", {})
    if isinstance(item, dict):
        print(json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2))
    print("Vault writes: false")


def _rebuild_payload(ctx: Any) -> dict[str, Any]:
    try:
        config = from_plugin_context(ctx)
        if config.vault_path is None:
            raise ConfigurationError("vault_path is not configured")
        result = rebuild_index(config.vault_path, config.index_path)
        return result.to_dict()
    except (ConfigurationError, NexusIndexError, OSError) as exc:
        return {"ok": False, "vault_writes": False, "errors": [str(exc)]}


def _search_payload(args: Namespace, ctx: Any) -> dict[str, Any]:
    try:
        config = from_plugin_context(ctx)
        results = search_index(
            config.index_path,
            args.query,
            kind=getattr(args, "kind", None),
            status=getattr(args, "status", None),
            limit=args.limit,
        )
        return {
            "ok": True,
            "query": args.query,
            "count": len(results),
            "items": [item.to_dict() for item in results],
            "vault_writes": False,
        }
    except (ConfigurationError, NexusIndexError, OSError) as exc:
        return {"ok": False, "vault_writes": False, "errors": [str(exc)]}


def _print_index_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False):
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    if "items" in payload:
        print(f"NEXUS search — {payload.get('count', 0)} result(s); Vault writes: false")
        for item in payload.get("items", []):
            if isinstance(item, dict):
                print(f"{item.get('id')}  {item.get('kind')}  {item.get('title')}")
        return
    print(
        f"NEXUS index rebuilt — {payload.get('records', 0)} record(s), "
        f"{payload.get('open_commitments', 0)} open commitment(s)"
    )
    print(f"index: {payload.get('index_path')}")
    print("Vault writes: false")


def _print_retention_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False):
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    print("NEXUS retention dry-run — no writes performed")
    for key in ("raw", "quarantine"):
        item = payload.get(key, {})
        if isinstance(item, dict):
            print(
                f"{key}: {item.get('total_files', 0)} file(s), "
                f"{item.get('expired_files', 0)} expired, "
                f"{item.get('expired_bytes', 0)} expired byte(s), "
                f"{item.get('unsafe_entries', 0)} unsafe entry(s)"
            )
    rejected = payload.get("rejected_candidates", {})
    if isinstance(rejected, dict):
        print(
            f"rejected candidates: {rejected.get('total_items', 0)} item(s), "
            f"{rejected.get('expired_items', 0)} expired"
        )


__all__ = ["configure_parser", "run_command"]
