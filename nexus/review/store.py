"""Private append-only review event store with deterministic replay."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..contracts import ReviewItem, ReviewStatus, SourceRef
from ..errors import ReviewStoreError
from ..fingerprints import stable_hash
from ..ids import IdPrefix, new_id
from ..serialization import to_primitive

try:
    import fcntl
except ImportError:  # pragma: no cover - NEXUS Phase 4 targets macOS/Linux.
    fcntl = None  # type: ignore[assignment]


EVENT_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _source_ref(payload: object) -> SourceRef:
    if not isinstance(payload, dict):
        raise ReviewStoreError("review source_ref must be an object")
    try:
        return SourceRef(
            source_id=payload["source_id"],
            conversation_id=payload["conversation_id"],
            span_ids=tuple(payload["span_ids"]),
            span_sha256=payload["span_sha256"],
            excerpt=payload.get("excerpt", ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewStoreError("review source_ref is invalid") from exc


def _review_item(payload: object) -> ReviewItem:
    if not isinstance(payload, dict):
        raise ReviewStoreError("review item must be an object")
    try:
        return ReviewItem(
            id=payload["id"],
            candidate_kind=payload["candidate_kind"],
            candidate_fingerprint=payload["candidate_fingerprint"],
            reason_codes=tuple(payload["reason_codes"]),
            candidate=dict(payload["candidate"]),
            source_refs=tuple(_source_ref(item) for item in payload["source_refs"]),
            status=ReviewStatus(payload["status"]),
            decision=payload.get("decision"),
            publication=payload.get("publication"),
            schema_version=payload.get("schema_version", 1),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewStoreError("review item is invalid") from exc


def create_review_item(
    *,
    candidate_kind: str,
    candidate: dict[str, Any],
    reason_codes: Iterable[str],
    source_refs: Iterable[SourceRef],
) -> ReviewItem:
    primitive = to_primitive(candidate)
    return ReviewItem(
        id=new_id(IdPrefix.REVIEW),
        candidate_kind=candidate_kind,
        candidate_fingerprint=stable_hash([candidate_kind, primitive]),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        candidate=dict(primitive),
        source_refs=tuple(source_refs),
    )


class ReviewStore:
    """Store review creates and decisions as an append-only private JSONL log."""

    def __init__(self, data_path: Path) -> None:
        self.directory = data_path / "review"
        self.path = self.directory / "events-v1.jsonl"

    def replay(self) -> dict[str, ReviewItem]:
        if self.directory.exists() and (
            self.directory.is_symlink() or not self.directory.is_dir()
        ):
            raise ReviewStoreError("review directory must be a real directory")
        if not self.path.exists():
            return {}
        if self.path.is_symlink() or not self.path.is_file():
            raise ReviewStoreError("review event store must be a regular non-symlink file")
        items: dict[str, ReviewItem] = {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ReviewStoreError("review event store could not be read") from exc
        for line_number, line in enumerate(lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReviewStoreError(
                    f"review event store is corrupt at line {line_number}"
                ) from exc
            if not isinstance(event, dict) or event.get("event_version") != EVENT_VERSION:
                raise ReviewStoreError(f"review event is invalid at line {line_number}")
            action = event.get("action")
            if action == "create":
                item = _review_item(event.get("item"))
                if item.id in items:
                    raise ReviewStoreError("duplicate review create event")
                items[item.id] = item
                continue
            if action == "publish":
                item_id = event.get("item_id")
                item = items.get(item_id)
                if item is None or item.status not in {
                    ReviewStatus.APPROVED,
                    ReviewStatus.EDITED,
                }:
                    raise ReviewStoreError("publication has no approved review decision")
                publication = event.get("publication")
                if not isinstance(publication, dict):
                    raise ReviewStoreError("review publication audit must be an object")
                if item.publication is not None:
                    raise ReviewStoreError("duplicate review publication event")
                items[item_id] = replace(item, publication=dict(publication))
                continue
            if action not in {"approve", "reject", "edit"}:
                raise ReviewStoreError(f"unknown review action at line {line_number}")
            item_id = event.get("item_id")
            item = items.get(item_id)
            if item is None or item.status is not ReviewStatus.PENDING:
                raise ReviewStoreError("review decision has no pending create event")
            status = {
                "approve": ReviewStatus.APPROVED,
                "reject": ReviewStatus.REJECTED,
                "edit": ReviewStatus.EDITED,
            }[action]
            candidate = event.get("candidate", item.candidate)
            if not isinstance(candidate, dict):
                raise ReviewStoreError("edited review candidate must be an object")
            decision = event.get("decision")
            if not isinstance(decision, dict):
                raise ReviewStoreError("review decision audit must be an object")
            items[item_id] = replace(
                item,
                status=status,
                candidate=dict(candidate),
                decision=dict(decision),
            )
        return items

    def list(self, *, status: ReviewStatus | None = None) -> tuple[ReviewItem, ...]:
        items = self.replay().values()
        return tuple(
            sorted(
                (item for item in items if status is None or item.status is status),
                key=lambda item: item.id,
            )
        )

    def get(self, item_id: str) -> ReviewItem:
        item = self.replay().get(item_id)
        if item is None:
            raise ReviewStoreError("review item was not found")
        return item

    def enqueue(self, item: ReviewItem) -> ReviewItem:
        existing = next(
            (
                value
                for value in self.replay().values()
                if value.candidate_fingerprint == item.candidate_fingerprint
            ),
            None,
        )
        if existing is not None:
            return existing
        self._append({"action": "create", "created_at": _now(), "item": to_primitive(item)})
        return item

    def decide(
        self,
        item_id: str,
        *,
        action: str,
        actor: str = "operator",
        reason: str | None = None,
        edited_candidate: dict[str, Any] | None = None,
    ) -> ReviewItem:
        if action not in {"approve", "reject", "edit"}:
            raise ReviewStoreError("review action must be approve, reject or edit")
        current = self.get(item_id)
        if current.status is not ReviewStatus.PENDING:
            raise ReviewStoreError("only pending review items can be decided")
        if action == "edit" and not edited_candidate:
            raise ReviewStoreError("edit requires a non-empty candidate object")
        if action != "edit" and edited_candidate is not None:
            raise ReviewStoreError("only edit can replace the candidate")
        if edited_candidate is not None and set(edited_candidate) != set(current.candidate):
            raise ReviewStoreError("edited candidate must preserve the original fields")
        decided_at = _now()
        decision = {
            "action": action,
            "actor": actor,
            "decided_at": decided_at,
            "reason": reason,
            "candidate_before_sha256": stable_hash(current.candidate),
            "candidate_after_sha256": stable_hash(
                edited_candidate if edited_candidate is not None else current.candidate
            ),
        }
        event: dict[str, Any] = {
            "action": action,
            "item_id": item_id,
            "decision": decision,
        }
        if edited_candidate is not None:
            event["candidate"] = to_primitive(edited_candidate)
        self._append(event)
        return self.get(item_id)

    def record_publication(
        self,
        item_id: str,
        *,
        record_id: str,
        content_sha256: str,
        run_id: str,
    ) -> ReviewItem:
        current = self.get(item_id)
        if current.status not in {ReviewStatus.APPROVED, ReviewStatus.EDITED}:
            raise ReviewStoreError("only approved or edited review items can be published")
        publication = {
            "record_id": record_id,
            "content_sha256": content_sha256,
            "run_id": run_id,
            "published_at": _now(),
        }
        if current.publication is not None:
            comparable = {
                key: current.publication.get(key) for key in ("record_id", "content_sha256")
            }
            expected = {key: publication[key] for key in comparable}
            if comparable != expected:
                raise ReviewStoreError("review item has a conflicting publication audit")
            return current
        self._append(
            {
                "action": "publish",
                "item_id": item_id,
                "publication": publication,
            }
        )
        return self.get(item_id)

    def _append(self, event: dict[str, Any]) -> None:
        if self.directory.exists() and self.directory.is_symlink():
            raise ReviewStoreError("review directory must not be a symlink")
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.directory, 0o700)
        except OSError as exc:
            raise ReviewStoreError("review directory could not be created securely") from exc
        if self.path.exists() and self.path.is_symlink():
            raise ReviewStoreError("review event store must not be a symlink")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        payload = dict(event)
        payload["event_version"] = EVENT_VERSION
        encoded = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        try:
            descriptor = os.open(self.path, flags, 0o600)
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise ReviewStoreError("review event could not be appended safely") from exc
