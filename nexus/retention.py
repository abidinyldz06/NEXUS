"""Read-only retention planning for private NEXUS data."""

from __future__ import annotations

import json
import os
import stat as stat_module
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import NexusConfig
from .contracts import ReviewStatus
from .errors import RetentionError
from .review import ReviewStore


@dataclass(frozen=True, slots=True)
class FileRetentionPlan:
    total_files: int = 0
    total_bytes: int = 0
    expired_files: int = 0
    expired_bytes: int = 0
    unsafe_entries: int = 0


@dataclass(frozen=True, slots=True)
class RejectedRetentionPlan:
    total_items: int = 0
    expired_items: int = 0
    expired_candidate_bytes: int = 0


@dataclass(frozen=True, slots=True)
class RetentionPlan:
    generated_at: str
    raw_cutoff: str
    rejected_cutoff: str
    raw: FileRetentionPlan
    quarantine: FileRetentionPlan
    rejected_candidates: RejectedRetentionPlan

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "dry-run",
            "writes_performed": False,
            "generated_at": self.generated_at,
            "raw_cutoff": self.raw_cutoff,
            "rejected_cutoff": self.rejected_cutoff,
            "raw": asdict(self.raw),
            "quarantine": asdict(self.quarantine),
            "rejected_candidates": asdict(self.rejected_candidates),
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RetentionError("retention time must be timezone-aware")
    return value.astimezone(UTC)


def _parse_instant(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise RetentionError("rejected review decision is missing decided_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RetentionError("rejected review decision has invalid decided_at") from exc
    return _utc(parsed)


def _validate_data_path(data_path: Path) -> Path:
    root = data_path.expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise RetentionError("data_path must be an absolute non-symlink path")
    if root.exists() and not root.is_dir():
        raise RetentionError("data_path must be a directory")
    return root


def _scan_files(root: Path, *, cutoff: datetime) -> FileRetentionPlan:
    if not root.exists():
        return FileRetentionPlan()
    if root.is_symlink() or not root.is_dir():
        raise RetentionError("retention root must be a real directory")

    total_files = total_bytes = expired_files = expired_bytes = unsafe_entries = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        safe_dirs: list[str] = []
        for name in sorted(dirnames):
            candidate = directory_path / name
            if candidate.is_symlink():
                unsafe_entries += 1
            else:
                safe_dirs.append(name)
        dirnames[:] = safe_dirs

        for name in sorted(filenames):
            candidate = directory_path / name
            try:
                file_stat = candidate.stat(follow_symlinks=False)
            except OSError:
                unsafe_entries += 1
                continue
            if candidate.is_symlink() or not stat_module.S_ISREG(file_stat.st_mode):
                unsafe_entries += 1
                continue
            total_files += 1
            total_bytes += file_stat.st_size
            modified_at = datetime.fromtimestamp(file_stat.st_mtime, tz=UTC)
            if modified_at <= cutoff:
                expired_files += 1
                expired_bytes += file_stat.st_size

    return FileRetentionPlan(
        total_files=total_files,
        total_bytes=total_bytes,
        expired_files=expired_files,
        expired_bytes=expired_bytes,
        unsafe_entries=unsafe_entries,
    )


def _scan_rejected(data_path: Path, *, cutoff: datetime) -> RejectedRetentionPlan:
    rejected = ReviewStore(data_path).list(status=ReviewStatus.REJECTED)
    expired_items = expired_candidate_bytes = 0
    for item in rejected:
        decision = item.decision
        if not isinstance(decision, dict):
            raise RetentionError("rejected review item is missing decision audit")
        if _parse_instant(decision.get("decided_at")) <= cutoff:
            expired_items += 1
            expired_candidate_bytes += len(
                json.dumps(
                    item.candidate,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
    return RejectedRetentionPlan(
        total_items=len(rejected),
        expired_items=expired_items,
        expired_candidate_bytes=expired_candidate_bytes,
    )


def plan_retention(config: NexusConfig, *, now: datetime | None = None) -> RetentionPlan:
    """Return aggregate expiry counts without creating, changing or deleting data."""
    instant = _utc(now or datetime.now(UTC))
    data_path = _validate_data_path(config.data_path)
    raw_cutoff = instant - timedelta(days=config.raw_retention_days)
    rejected_cutoff = instant - timedelta(days=config.rejected_retention_days)
    return RetentionPlan(
        generated_at=instant.isoformat().replace("+00:00", "Z"),
        raw_cutoff=raw_cutoff.isoformat().replace("+00:00", "Z"),
        rejected_cutoff=rejected_cutoff.isoformat().replace("+00:00", "Z"),
        raw=_scan_files(data_path / "raw", cutoff=raw_cutoff),
        quarantine=_scan_files(data_path / "quarantine", cutoff=rejected_cutoff),
        rejected_candidates=_scan_rejected(data_path, cutoff=rejected_cutoff),
    )


__all__ = ["RetentionPlan", "plan_retention"]
