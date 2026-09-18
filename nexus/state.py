"""Small private source-lineage registry for Phase 2 idempotency."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import SourceType
from .errors import StateError
from .fingerprints import source_lineage_key
from .ids import IdPrefix, is_nexus_id, new_id


STATE_VERSION = 1


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class SourceObservation:
    source_id: str
    lineage_key: str
    revision: int
    content_sha256: str
    duplicate: bool


class SourceStateStore:
    """Atomic JSON state; canonical memory remains elsewhere."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        if not self.path.is_absolute() or self.path.is_symlink():
            raise StateError("state path must be absolute and not a symlink")
        parent = self.path.parent
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise StateError("state directory must be a real directory")
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"state_version": STATE_VERSION, "sources": {}}
        if not self.path.is_file() or self.path.is_symlink():
            raise StateError("state path must be a regular file")
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateError("source state is unreadable or corrupt") from exc
        if not isinstance(state, dict) or state.get("state_version") != STATE_VERSION:
            raise StateError("unsupported source state version")
        if not isinstance(state.get("sources"), dict):
            raise StateError("source state has no sources mapping")
        return state

    def observe(
        self, *, source_type: SourceType, external_id: str | None, content_sha256: str
    ) -> SourceObservation:
        if not isinstance(source_type, SourceType):
            raise StateError("source_type must be a SourceType")
        if not _valid_sha256(content_sha256):
            raise StateError("content_sha256 must be a lowercase SHA-256 hex digest")
        lineage_key = source_lineage_key(source_type, external_id, content_sha256)
        sources: dict[str, Any] = self._state["sources"]
        entry = sources.get(lineage_key)
        if entry is None:
            observation = SourceObservation(
                source_id=new_id(IdPrefix.SOURCE),
                lineage_key=lineage_key,
                revision=1,
                content_sha256=content_sha256,
                duplicate=False,
            )
            sources[lineage_key] = {
                "source_id": observation.source_id,
                "source_type": source_type.value,
                "external_id": external_id,
                "latest_revision": 1,
                "latest_content_sha256": content_sha256,
                "revisions": [content_sha256],
            }
            self._save()
            return observation

        self._validate_entry(entry, lineage_key)
        if entry["latest_content_sha256"] == content_sha256:
            return SourceObservation(
                source_id=entry["source_id"],
                lineage_key=lineage_key,
                revision=entry["latest_revision"],
                content_sha256=content_sha256,
                duplicate=True,
            )
        revision = int(entry["latest_revision"]) + 1
        entry["latest_revision"] = revision
        entry["latest_content_sha256"] = content_sha256
        entry["revisions"].append(content_sha256)
        self._save()
        return SourceObservation(
            source_id=entry["source_id"],
            lineage_key=lineage_key,
            revision=revision,
            content_sha256=content_sha256,
            duplicate=False,
        )

    def lookup(
        self, *, source_type: SourceType, external_id: str | None, content_sha256: str
    ) -> SourceObservation | None:
        if not isinstance(source_type, SourceType) or not _valid_sha256(content_sha256):
            raise StateError("invalid source lookup identity")
        key = source_lineage_key(source_type, external_id, content_sha256)
        entry = self._state["sources"].get(key)
        if entry is None:
            return None
        self._validate_entry(entry, key)
        return SourceObservation(
            source_id=entry["source_id"],
            lineage_key=key,
            revision=entry["latest_revision"],
            content_sha256=entry["latest_content_sha256"],
            duplicate=entry["latest_content_sha256"] == content_sha256,
        )

    @staticmethod
    def _validate_entry(entry: Any, lineage_key: str) -> None:
        if not isinstance(entry, dict):
            raise StateError(f"invalid source state entry: {lineage_key}")
        if not is_nexus_id(entry.get("source_id"), IdPrefix.SOURCE):
            raise StateError(f"invalid source id in state: {lineage_key}")
        revision = entry.get("latest_revision")
        revisions = entry.get("revisions")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(revisions, list)
            or len(revisions) != revision
            or not _valid_sha256(entry.get("latest_content_sha256"))
            or any(not _valid_sha256(item) for item in revisions)
        ):
            raise StateError(f"invalid source revisions in state: {lineage_key}")

    def _save(self) -> None:
        parent = self.path.parent
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise StateError("state directory must be a real directory")
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if parent.is_symlink():
            raise StateError("state directory must not be a symlink")
        os.chmod(parent, 0o700)
        payload = json.dumps(self._state, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=parent, prefix=".nexus-state-", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        os.chmod(self.path, 0o600)
