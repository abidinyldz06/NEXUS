"""CLI handlers for the private Phase 4 review queue."""

from __future__ import annotations

import json
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any

from ..contracts import ReviewStatus
from ..errors import ReviewStoreError
from ..serialization import to_primitive
from .store import ReviewStore

MAX_EDIT_BYTES = 1024 * 1024


def configure_review_parser(parser: ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="review_command")
    list_command = commands.add_parser("list", help="List review items")
    list_command.add_argument(
        "--status", choices=[item.value for item in ReviewStatus], default="pending"
    )
    list_command.add_argument("--json", action="store_true", dest="as_json")

    show = commands.add_parser("show", help="Show one review item")
    show.add_argument("item_id")
    show.add_argument("--json", action="store_true", dest="as_json")

    for action in ("approve", "reject"):
        command = commands.add_parser(action, help=f"{action.title()} one pending item")
        command.add_argument("item_id")
        command.add_argument("--reason")
        command.add_argument("--json", action="store_true", dest="as_json")

    edit = commands.add_parser("edit", help="Approve with an edited candidate JSON object")
    edit.add_argument("item_id")
    edit.add_argument("--candidate-file", required=True)
    edit.add_argument("--reason")
    edit.add_argument("--json", action="store_true", dest="as_json")


def _load_candidate(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise ReviewStoreError("candidate file path must be absolute")
    if path.is_symlink() or not path.is_file():
        raise ReviewStoreError("candidate file must be a regular non-symlink file")
    if path.stat().st_size > MAX_EDIT_BYTES:
        raise ReviewStoreError("candidate file exceeds the 1 MiB limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewStoreError("candidate file must contain valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or not value:
        raise ReviewStoreError("candidate file must contain a non-empty JSON object")
    return value


def run_review_command(args: Namespace, *, data_path: Path) -> tuple[int, dict[str, Any]]:
    store = ReviewStore(data_path)
    command = getattr(args, "review_command", None)
    try:
        if command == "list":
            status = ReviewStatus(args.status)
            items = [to_primitive(item) for item in store.list(status=status)]
            return 0, {"ok": True, "items": items, "vault_writes": False}
        if command == "show":
            return 0, {
                "ok": True,
                "item": to_primitive(store.get(args.item_id)),
                "vault_writes": False,
            }
        if command in {"approve", "reject"}:
            item = store.decide(args.item_id, action=command, reason=args.reason)
            return 0, {"ok": True, "item": to_primitive(item), "vault_writes": False}
        if command == "edit":
            item = store.decide(
                args.item_id,
                action="edit",
                reason=args.reason,
                edited_candidate=_load_candidate(args.candidate_file),
            )
            return 0, {"ok": True, "item": to_primitive(item), "vault_writes": False}
        return 2, {"ok": False, "errors": ["review subcommand is required"]}
    except ReviewStoreError as exc:
        return 2, {"ok": False, "errors": [str(exc)], "vault_writes": False}
