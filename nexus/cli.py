"""Read-only Phase 2 Hermes CLI surface."""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from typing import Any, Callable

from . import __version__
from .config import from_plugin_context
from .errors import ConfigurationError
from .ingest import plan_inbox


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

    parser.set_defaults(func=handler)


def _status_payload(ctx: Any) -> dict[str, Any]:
    try:
        config = from_plugin_context(ctx)
    except ConfigurationError as exc:
        return {
            "ok": False,
            "version": __version__,
            "phase": "0-3-shadow",
            "write_enabled": False,
            "errors": [str(exc)],
        }

    errors = list(config.validate_existing_paths())
    return {
        "ok": not errors,
        "version": __version__,
        "phase": "0-3-shadow",
        "write_enabled": False,
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
    print("Writes: disabled (Phase 3 shadow-mode safety gate)")
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
    print("Usage: hermes nexus {status|config validate|ingest --dry-run}")
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


__all__ = ["configure_parser", "run_command"]
