"""NEXUS CLI with explicit shadow and private-review safety boundaries."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .config import from_plugin_context
from .decision import route_text
from .errors import (
    ConfigurationError,
    DecisionError,
    ExtractionError,
    NexusError,
    NexusIndexError,
)
from .eval import (
    PrivateEvalFixture,
    evaluate_with_llm_report,
    frozen_fixture_path,
    load_private_fixture,
)
from .forget import apply_forget, plan_forget
from .git_rollback_drill import run_synthetic_git_rollback_drill
from .index import rebuild_index, search_index
from .ingest import plan_inbox, shadow_inbox_source, stage_inbox_source
from .ingest_v2 import (
    pause_ingest,
    repair_missing_canonical,
    reprocess_failed,
    review_queue_payload,
    rollback_batch,
    run_inbox,
    status_payload,
    unpause_ingest,
    acceptance_report,
    write_human_review_pack,
)
from .permission_audit import audit_permissions
from .publication import apply_publication, plan_publication
from .pulse import emit_due_reminders
from .restore_drill import run_synthetic_restore_drill
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

    ingest = subcommands.add_parser("ingest", help="Inspect or stage exact Inbox sources")
    ingest_mode = ingest.add_mutually_exclusive_group()
    ingest_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Required safety gate; parse and report without archiving or publishing",
    )
    ingest_mode.add_argument(
        "--shadow",
        action="store_true",
        help="Extract one exact source without persisting candidates",
    )
    ingest_mode.add_argument(
        "--stage",
        action="store_true",
        help="Archive and stage one exact source into the private review queue",
    )
    ingest.add_argument(
        "--source", help="Inbox-relative source path; required with --shadow or --stage"
    )
    ingest.add_argument(
        "--conversation",
        help="Exact external conversation ID; required when the source contains more than one",
    )
    ingest.add_argument(
        "--confirm-sha",
        help="Exact lowercase source SHA-256; required with --shadow or --stage",
    )
    ingest.add_argument(
        "--max-segments",
        type=int,
        default=20,
        help="Maximum model calls for one shadow/stage run (1-100; default: 20)",
    )
    ingest.add_argument(
        "--long-unit-budget",
        nargs="?",
        const=300,
        type=int,
        default=None,
        metavar="SECONDS",
        help="Human-triggered long-unit lane for oversized turns (default 300s). Logged.",
    )
    ingest.add_argument(
        "--canary-write",
        action="store_true",
        help="Write accepted memories under Nexus/. Requires --confirm canary. Max 25/day.",
    )
    ingest.add_argument(
        "--confirm",
        dest="ingest_confirm",
        help="Exact confirm token; --canary-write requires canary",
    )
    ingest.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")
    ingest_commands = ingest.add_subparsers(dest="ingest_command", required=False)
    ingest_status = ingest_commands.add_parser(
        "status", help="Show resumable ingest metadata without calling a model"
    )
    ingest_status.add_argument("ingest_id", nargs="?", help="Optional ingest id")
    ingest_status.add_argument(
        "--json", action="store_true", dest="status_json", help="Emit JSON"
    )
    ingest_pause = ingest_commands.add_parser(
        "pause", help="Stop live vault writes; shadow log remains"
    )
    ingest_pause.add_argument(
        "--json", action="store_true", dest="pause_json", help="Emit JSON"
    )
    ingest_unpause = ingest_commands.add_parser(
        "unpause", help="Clear the pause flag without extracting or writing"
    )
    ingest_unpause.add_argument(
        "--json", action="store_true", dest="unpause_json", help="Emit JSON"
    )
    ingest_rollback = ingest_commands.add_parser(
        "rollback", help="Tombstone one ingest batch; default dry-run"
    )
    ingest_rollback.add_argument("ingest_id", help="Batch ingest id to retract")
    ingest_rollback.add_argument(
        "--dry-run",
        action="store_true",
        dest="rollback_dry_run",
        help="List matching ledger ids without writing (default)",
    )
    ingest_rollback.add_argument(
        "--apply",
        action="store_true",
        dest="rollback_apply",
        help="Retract matching ledger rows and tombstone Vault files; requires --confirm",
    )
    ingest_rollback.add_argument(
        "--confirm",
        dest="rollback_confirm",
        help="Must equal ingest_id when --apply is set",
    )
    ingest_rollback.add_argument(
        "--json", action="store_true", dest="rollback_json", help="Emit JSON"
    )
    ingest_reprocess = ingest_commands.add_parser(
        "reprocess", help="Arm FAILED_SEGMENT rows for the next run without extracting"
    )
    ingest_reprocess.add_argument("ingest_id", help="Ingest id whose failed segments should retry")
    ingest_reprocess.add_argument(
        "--json", action="store_true", dest="reprocess_json", help="Emit JSON"
    )
    ingest_queue = ingest_commands.add_parser(
        "queue", help="List the review/reprocess queue without calling a model"
    )
    ingest_queue.add_argument(
        "--json", action="store_true", dest="queue_json", help="Emit JSON"
    )
    ingest_report = ingest_commands.add_parser(
        "report", help="Emit a PII-free ingest acceptance rollup without extracting"
    )
    ingest_report.add_argument(
        "--json", action="store_true", dest="report_json", help="Emit JSON"
    )
    ingest_repair = ingest_commands.add_parser(
        "repair-canonical",
        help="Write ledger rows that have no Vault file; does not extract",
    )
    ingest_repair.add_argument(
        "--dry-run",
        action="store_true",
        dest="repair_dry_run",
        help="Count missing Vault files without writing (default)",
    )
    ingest_repair.add_argument(
        "--apply",
        action="store_true",
        dest="repair_apply",
        help="Write missing canonical files; requires --confirm repair",
    )
    ingest_repair.add_argument(
        "--confirm",
        dest="repair_confirm",
        help="Must equal repair when --apply is set",
    )
    ingest_repair.add_argument(
        "--json", action="store_true", dest="repair_json", help="Emit JSON"
    )
    ingest_pack = ingest_commands.add_parser(
        "review-pack",
        help="Copy canonical memories under data_path for private human scoring",
    )
    ingest_pack.add_argument(
        "--dest",
        dest="pack_dest",
        help="Absolute directory under data_path (default: data_path/a8-human-review)",
    )
    ingest_pack.add_argument(
        "--json", action="store_true", dest="pack_json", help="Emit JSON"
    )

    eval_command = subcommands.add_parser(
        "eval", help="Run the packaged frozen holdout without publishing"
    )
    eval_command.add_argument(
        "--shadow",
        action="store_true",
        help="Required safety gate; call the model but do not persist candidates",
    )
    eval_command.add_argument(
        "--private-dataset",
        metavar="JSON_BASENAME",
        help="Evaluate one SHA-confirmed fixture from data_path/eval/private",
    )
    eval_command.add_argument(
        "--confirm-sha",
        metavar="SHA256",
        help="Exact lowercase SHA-256 required with --private-dataset",
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

    route = subcommands.add_parser(
        "route", help="Shadow-classify one utterance without executing or writing"
    )
    route.add_argument(
        "--shadow",
        action="store_true",
        help="Required safety gate; classify but never execute, store or publish",
    )
    route.add_argument("--text", help="Utterance to classify; never written to disk")
    route.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

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

    forget = subcommands.add_parser(
        "forget", help="Inspect or explicitly forget one canonical record"
    )
    forget.add_argument("record_id", help="Exact canonical NEXUS record ID")
    forget_mode = forget.add_mutually_exclusive_group(required=True)
    forget_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report dependency impact without writing",
    )
    forget_mode.add_argument(
        "--apply",
        action="store_true",
        help="Delete the unreferenced target and rebuild derived state",
    )
    forget.add_argument(
        "--confirm",
        metavar="RECORD_ID",
        help="Required with --apply; must exactly match the target ID",
    )
    forget.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    audit = subcommands.add_parser("audit", help="Run read-only local safety audits")
    audit_subcommands = audit.add_subparsers(dest="audit_command")
    permissions = audit_subcommands.add_parser(
        "permissions", help="Check private path ownership and access bits"
    )
    permissions.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

    drill = subcommands.add_parser("drill", help="Run isolated synthetic recovery checks")
    drill_subcommands = drill.add_subparsers(dest="drill_command")
    restore = drill_subcommands.add_parser(
        "restore", help="Verify synthetic snapshot, restore and index parity"
    )
    restore.add_argument(
        "--synthetic",
        action="store_true",
        help="Required safety gate; use temporary synthetic data only",
    )
    restore.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")
    git_rollback = drill_subcommands.add_parser(
        "git-rollback", help="Verify an external git-dir rollback with synthetic files"
    )
    git_rollback.add_argument(
        "--synthetic",
        action="store_true",
        help="Required safety gate; use temporary synthetic files only",
    )
    git_rollback.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON")

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
        "write_scope": (
            "explicit-confirmed-operations"
            if not errors and config.write_ready
            else "none"
        ),
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
        print(
            "Vault writes: explicit confirmed publish/forget and reminder-state "
            "operations only; auto-publish disabled"
        )
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
        if getattr(args, "ingest_command", None) == "pause":
            try:
                config = from_plugin_context(ctx)
                payload = pause_ingest(config)
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "paused": False,
                    "writes_performed": False,
                    "vault_writes": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "pause_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "unpause":
            try:
                config = from_plugin_context(ctx)
                payload = unpause_ingest(config)
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "paused": True,
                    "writes_performed": False,
                    "vault_writes": False,
                    "extraction_called": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "unpause_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "status":
            try:
                config = from_plugin_context(ctx)
                payload = status_payload(config, getattr(args, "ingest_id", None))
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "ingest_pipeline_v2": False,
                    "mode": "shadow-only",
                    "extraction_called": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "status_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "rollback":
            try:
                config = from_plugin_context(ctx)
                payload = rollback_batch(
                    config,
                    str(getattr(args, "ingest_id", "") or ""),
                    apply=bool(getattr(args, "rollback_apply", False)),
                    confirm=getattr(args, "rollback_confirm", None),
                )
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "writes_performed": False,
                    "vault_writes": False,
                    "extraction_called": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "rollback_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "reprocess":
            try:
                config = from_plugin_context(ctx)
                payload = reprocess_failed(config, str(getattr(args, "ingest_id", "") or ""))
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "writes_performed": False,
                    "vault_writes": False,
                    "extraction_called": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "reprocess_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "queue":
            try:
                config = from_plugin_context(ctx)
                payload = review_queue_payload(config)
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "count": 0,
                    "items": [],
                    "extraction_called": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "queue_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "report":
            try:
                config = from_plugin_context(ctx)
                payload = acceptance_report(config)
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "extraction_called": False,
                    "vault_writes": False,
                    "unmeasured_counted_as_pass": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "report_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "repair-canonical":
            try:
                config = from_plugin_context(ctx)
                payload = repair_missing_canonical(
                    config,
                    confirm=getattr(args, "repair_confirm", None),
                    apply=bool(getattr(args, "repair_apply", False)),
                )
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "missing_count": 0,
                    "extraction_called": False,
                    "vault_writes": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "repair_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        if getattr(args, "ingest_command", None) == "review-pack":
            try:
                config = from_plugin_context(ctx)
                dest_value = getattr(args, "pack_dest", None)
                dest = (
                    Path(dest_value).expanduser()
                    if dest_value
                    else config.data_path / "a8-human-review"
                )
                payload = write_human_review_pack(config, dest)
            except (NexusError, OSError, ValueError) as exc:
                payload = {
                    "ok": False,
                    "copied": 0,
                    "quality_declared": False,
                    "extraction_called": False,
                    "vault_writes": False,
                    "errors": [type(exc).__name__],
                }
            _print_payload(
                payload,
                as_json=bool(
                    getattr(args, "pack_json", False) or getattr(args, "as_json", False)
                ),
            )
            return 0 if payload.get("ok") else 2
        dry_run = bool(getattr(args, "dry_run", False))
        shadow = bool(getattr(args, "shadow", False))
        stage = bool(getattr(args, "stage", False))
        if not dry_run and not shadow and not stage:
            print("NEXUS ingest requires exactly one of: --dry-run, --shadow or --stage")
            return 2
        try:
            config = from_plugin_context(ctx)
            if dry_run:
                if (
                    getattr(args, "source", None)
                    or getattr(args, "conversation", None)
                    or getattr(args, "confirm_sha", None)
                    or getattr(args, "max_segments", 20) != 20
                ):
                    raise ValueError(
                        "source selection options are only valid with --shadow or --stage"
                    )
                payload = plan_inbox(config).to_dict()
            else:
                if not getattr(args, "source", None) or not getattr(args, "confirm_sha", None):
                    raise ValueError(
                        f"--{'stage' if stage else 'shadow'} requires --source and --confirm-sha"
                    )
                if config.ingest_pipeline_v2:
                    payload = run_inbox(
                        config,
                        ctx.llm,
                        relative_path=args.source,
                        confirmed_sha256=args.confirm_sha,
                        conversation_id=getattr(args, "conversation", None),
                        max_segments=args.max_segments,
                        long_unit_budget=getattr(args, "long_unit_budget", None),
                        canary_write=bool(getattr(args, "canary_write", False)),
                        confirm=getattr(args, "ingest_confirm", None),
                    ).to_dict()
                    wrote = bool(payload.get("vault_written"))
                    payload["writes_performed"] = wrote
                    payload["vault_writes"] = wrote
                    payload["candidates_published"] = False
                    payload["mode"] = "v2-canary" if getattr(args, "canary_write", False) else "v2"
                else:
                    runner = stage_inbox_source if stage else shadow_inbox_source
                    payload = runner(
                        config,
                        ctx.llm,
                        relative_path=args.source,
                        confirmed_sha256=args.confirm_sha,
                        conversation_id=getattr(args, "conversation", None),
                        max_segments=args.max_segments,
                    ).to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "stage" if stage else "shadow" if shadow else "dry-run",
                "writes_performed": False,
                "vault_writes": False,
                "candidates_published": False,
                "errors": [str(exc)],
            }
            if isinstance(exc, ExtractionError):
                payload["failure_class"] = exc.failure_class
        _print_ingest_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "eval":
        if not bool(getattr(args, "shadow", False)):
            print("Phase 3 only supports: hermes nexus eval --shadow")
            return 2
        private_dataset = getattr(args, "private_dataset", None)
        confirmed_sha256 = getattr(args, "confirm_sha", None)
        try:
            if private_dataset is None:
                if confirmed_sha256 is not None:
                    raise ValueError("--confirm-sha is only valid with --private-dataset")
                fixture = frozen_fixture_path()
                dataset_kind = "frozen"
            else:
                if confirmed_sha256 is None:
                    raise ValueError("--private-dataset requires --confirm-sha")
                fixture = load_private_fixture(
                    from_plugin_context(ctx).data_path,
                    private_dataset,
                    confirmed_sha256,
                )
                dataset_kind = "private"
            payload = _shadow_eval_payload(ctx, fixture, dataset_kind=dataset_kind)
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "shadow",
                "dataset": "private" if private_dataset is not None else "frozen",
                "writes_performed": False,
                "candidates_published": False,
                "errors": [str(exc)],
            }
        _print_eval_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "review":
        try:
            config = from_plugin_context(ctx)
            if getattr(args, "review_command", None) == "publish":
                if bool(getattr(args, "apply", False)):
                    payload = apply_publication(
                        config,
                        args.item_id,
                        confirmation=getattr(args, "confirm", None),
                    ).to_dict()
                else:
                    if getattr(args, "confirm", None) is not None:
                        raise ValueError("--confirm is only valid with --apply")
                    payload = plan_publication(config, args.item_id).to_dict()
                result = 0
            else:
                result, payload = run_review_command(args, data_path=config.data_path)
        except (NexusError, OSError, ValueError) as exc:
            result, payload = 2, {
                "ok": False,
                "errors": [str(exc)],
                "vault_writes": False,
                "writes_performed": False,
            }
        _print_review_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return result
    if command == "rebuild":
        payload = _rebuild_payload(ctx)
        _print_index_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "route":
        if not bool(getattr(args, "shadow", False)):
            print("Phase A only supports: hermes nexus route --shadow")
            return 2
        try:
            if not getattr(args, "text", None):
                raise DecisionError("route --shadow requires --text")
            payload = route_text(
                args.text,
                from_plugin_context(ctx),
                llm=getattr(ctx, "llm", None),
            ).to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "shadow",
                "writes_performed": False,
                "would_execute": False,
                "errors": [str(exc)],
            }
        _print_route_payload(payload, as_json=bool(getattr(args, "as_json", False)))
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
    if command == "forget":
        try:
            config = from_plugin_context(ctx)
            if bool(getattr(args, "apply", False)):
                payload = apply_forget(
                    config,
                    args.record_id,
                    confirmation=getattr(args, "confirm", None),
                ).to_dict()
            else:
                if getattr(args, "confirm", None) is not None:
                    raise ValueError("--confirm is only valid with --apply")
                payload = plan_forget(config, args.record_id).to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "confirmed-apply"
                if bool(getattr(args, "apply", False))
                else "dry-run",
                "writes_performed": False,
                "errors": [str(exc)],
            }
        _print_forget_payload(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "audit" and getattr(args, "audit_command", None) == "permissions":
        try:
            payload = audit_permissions(from_plugin_context(ctx)).to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "read-only",
                "writes_performed": False,
                "errors": [str(exc)],
            }
        _print_permission_audit(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "drill" and getattr(args, "drill_command", None) == "restore":
        if not bool(getattr(args, "synthetic", False)):
            print("Phase 8 only supports: hermes nexus drill restore --synthetic")
            return 2
        try:
            payload = run_synthetic_restore_drill().to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "synthetic-temporary",
                "production_paths_accessed": False,
                "production_writes": False,
                "errors": [str(exc)],
            }
        _print_restore_drill(payload, as_json=bool(getattr(args, "as_json", False)))
        return 0 if payload["ok"] else 2
    if command == "drill" and getattr(args, "drill_command", None) == "git-rollback":
        if not bool(getattr(args, "synthetic", False)):
            print("Phase 8 only supports: hermes nexus drill git-rollback --synthetic")
            return 2
        try:
            payload = run_synthetic_git_rollback_drill().to_dict()
        except (NexusError, OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "mode": "synthetic-temporary",
                "production_paths_accessed": False,
                "production_writes": False,
                "errors": [str(exc)],
            }
        _print_git_rollback_drill(
            payload, as_json=bool(getattr(args, "as_json", False))
        )
        return 0 if payload["ok"] else 2
    print(
        "Usage: hermes nexus "
        "{status|config validate|ingest {--dry-run|--shadow|--stage|status|pause}|eval --shadow|review ...|"
        "rebuild|route --shadow|search|reminders --emit-local|retention --dry-run|forget ...|"
        "audit permissions|drill restore --synthetic|drill git-rollback --synthetic}"
    )
    return 2


def _print_ingest_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if payload.get("mode") in {"shadow", "stage"}:
        source = payload.get("source", {})
        extraction = payload.get("extraction", {})
        if payload.get("mode") == "stage":
            print("NEXUS ingest stage — private review state only; no Vault publication")
        else:
            print("NEXUS ingest shadow — no writes or publication")
        if isinstance(source, dict) and isinstance(extraction, dict):
            print(
                f"conversations: {source.get('conversations', 0)}, "
                f"messages: {source.get('messages', 0)}, "
                f"segments: {extraction.get('segments', 0)}, "
                f"candidates: {extraction.get('candidates', 0)}"
            )
        review = payload.get("review", {})
        if isinstance(review, dict) and payload.get("mode") == "stage":
            print(
                f"review created: {review.get('created', 0)}, "
                f"reused: {review.get('reused', 0)}"
            )
        for error in payload.get("errors", []):
            print(f"error: {error}")
        if payload.get("failure_class"):
            print(f"failure_class: {payload['failure_class']}")
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


def _shadow_eval_payload(
    ctx: Any,
    fixture: Path | PrivateEvalFixture,
    *,
    dataset_kind: str,
) -> dict[str, Any]:
    try:
        report = evaluate_with_llm_report(fixture, ctx.llm)
    except Exception:
        return {
            "ok": False,
            "mode": "shadow",
            "dataset": dataset_kind,
            "writes_performed": False,
            "candidates_published": False,
            "errors": ["shadow evaluation failed without exposing provider details"],
        }
    return {
        "ok": report.accepted,
        "mode": "shadow",
        "dataset": dataset_kind,
        "writes_performed": False,
        "candidates_published": False,
        "report": report.to_dict(),
        "errors": []
        if report.accepted
        else [f"{dataset_kind} dataset acceptance thresholds were not met"],
    }


def _print_eval_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(
        f"NEXUS {payload.get('dataset', 'frozen')} evaluation — "
        "shadow mode; no candidates published"
    )
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
                f"precision: {metrics.get('expected_kind_precision', 0):.2f}, "
                f"exact-case: {metrics.get('exact_case_match_rate', 0):.2f}, "
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
    if payload.get("mode") == "dry-run" and "record_id" in payload:
        print(
            f"NEXUS publish dry-run — {payload.get('review_id')} -> "
            f"{payload.get('record_id')}; no writes performed"
        )
        return
    if payload.get("mode") == "confirmed-apply":
        print(
            f"NEXUS publish complete — {payload.get('record_id')}; "
            f"already published: {str(bool(payload.get('already_published'))).lower()}"
        )
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


def _print_route_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print("NEXUS route shadow — no execution, writes or publication")
    if payload.get("ok", False):
        print(
            f"category: {payload.get('category')}, "
            f"confidence: {payload.get('confidence')}, "
            f"backend: {payload.get('backend')}, "
            f"would_execute: {str(bool(payload.get('would_execute'))).lower()}"
        )
        print(
            f"external classifier: {str(bool(payload.get('external_classifier_invoked'))).lower()}, "
            f"needs review: {str(bool(payload.get('needs_human_review'))).lower()}, "
            f"review band: {payload.get('review_band')}"
        )
    for error in payload.get("errors", []):
        print(f"error: {error}")


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


def _print_forget_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False):
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    if payload.get("mode") == "dry-run":
        print("NEXUS forget dry-run — no writes performed")
        print(
            f"target: {payload.get('record_id')} ({payload.get('record_kind')}), "
            f"dependencies: {payload.get('dependency_count', 0)}, "
            f"can apply: {str(bool(payload.get('can_apply'))).lower()}"
        )
        return
    print(
        f"NEXUS forget complete — {payload.get('record_id')} deleted; "
        f"{payload.get('records_after', 0)} canonical record(s) remain"
    )


def _print_permission_audit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False) and "private_data" not in payload:
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    print("NEXUS permission audit — read-only; no writes performed")
    for key in ("private_data", "inbox"):
        item = payload.get(key, {})
        if isinstance(item, dict):
            state = "absent" if not item.get("present", False) else "present"
            print(
                f"{key}: {state}, {item.get('checked_entries', 0)} checked, "
                f"{item.get('insecure_entries', 0)} insecure, "
                f"{item.get('unsafe_entries', 0)} unsafe"
            )


def _print_restore_drill(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False):
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    print("NEXUS restore drill — synthetic temporary data only")
    print(
        f"records: {payload.get('records', 0)}, "
        f"open commitments: {payload.get('open_commitments', 0)}, "
        f"canonical files: {payload.get('canonical_files', 0)}"
    )
    print(
        f"hash parity: {payload.get('canonical_hashes_match', False)}, "
        f"index parity: {payload.get('index_parity', False)}, "
        f"cleanup: {payload.get('cleanup_verified', False)}"
    )
    print("Production paths accessed: false; production writes: false")


def _print_git_rollback_drill(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    if not payload.get("ok", False):
        for error in payload.get("errors", []):
            print(f"error: {error}")
        return
    print("NEXUS Git rollback drill — synthetic temporary data only")
    print(
        f"files: {payload.get('files', 0)}, "
        f"metadata external: {payload.get('metadata_external', False)}, "
        f"mutation detected: {payload.get('mutation_detected', False)}"
    )
    print(
        f"rollback parity: {payload.get('rollback_hashes_match', False)}, "
        f"clean: {payload.get('clean_after_rollback', False)}, "
        f"cleanup: {payload.get('cleanup_verified', False)}"
    )
    print("Production paths accessed: false; production writes: false")


__all__ = ["configure_parser", "run_command"]
