"""Read-only permission audit for private NEXUS paths."""

from __future__ import annotations

import os
import stat as stat_module
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import NexusConfig


@dataclass(frozen=True, slots=True)
class ScopeAudit:
    present: bool
    checked_entries: int = 0
    insecure_entries: int = 0
    unsafe_entries: int = 0
    issues_by_reason: tuple[tuple[str, int], ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["issues_by_reason"] = dict(self.issues_by_reason)
        return payload


@dataclass(frozen=True, slots=True)
class PermissionAuditReport:
    private_data: ScopeAudit
    inbox: ScopeAudit

    @property
    def ok(self) -> bool:
        return all(
            scope.insecure_entries == 0 and scope.unsafe_entries == 0
            for scope in (self.private_data, self.inbox)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": "read-only",
            "writes_performed": False,
            "private_data": self.private_data.to_dict(),
            "inbox": self.inbox.to_dict(),
        }


def _scan_scope(root: Path) -> ScopeAudit:
    if not root.exists() and not root.is_symlink():
        return ScopeAudit(present=False)

    checked = 0
    insecure: set[str] = set()
    unsafe: set[str] = set()
    reasons: dict[str, int] = {}
    expected_uid = os.getuid() if hasattr(os, "getuid") else None

    def issue(reason: str, key: str, *, is_unsafe: bool = False) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1
        (unsafe if is_unsafe else insecure).add(key)

    def inspect(path: Path, key: str, *, require_directory: bool = False) -> bool:
        nonlocal checked
        try:
            metadata = path.lstat()
        except OSError:
            issue("unreadable", key, is_unsafe=True)
            return False
        if stat_module.S_ISLNK(metadata.st_mode):
            issue("symlink", key, is_unsafe=True)
            return False
        if require_directory and not stat_module.S_ISDIR(metadata.st_mode):
            issue("not_directory", key, is_unsafe=True)
            return False
        if not require_directory and not (
            stat_module.S_ISDIR(metadata.st_mode) or stat_module.S_ISREG(metadata.st_mode)
        ):
            issue("unsupported_type", key, is_unsafe=True)
            return False
        checked += 1
        if stat_module.S_IMODE(metadata.st_mode) & 0o077:
            issue("group_or_world_access", key)
        if expected_uid is not None and metadata.st_uid != expected_uid:
            issue("owner_mismatch", key)
        return True

    if not inspect(root, ".", require_directory=True):
        return ScopeAudit(
            present=True,
            checked_entries=checked,
            insecure_entries=len(insecure),
            unsafe_entries=len(unsafe),
            issues_by_reason=tuple(sorted(reasons.items())),
        )

    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        safe_dirs: list[str] = []
        for name in sorted(dirnames):
            candidate = directory_path / name
            key = candidate.relative_to(root).as_posix()
            if inspect(candidate, key, require_directory=True):
                safe_dirs.append(name)
        dirnames[:] = safe_dirs
        for name in sorted(filenames):
            candidate = directory_path / name
            inspect(candidate, candidate.relative_to(root).as_posix())

    return ScopeAudit(
        present=True,
        checked_entries=checked,
        insecure_entries=len(insecure),
        unsafe_entries=len(unsafe),
        issues_by_reason=tuple(sorted(reasons.items())),
    )


def audit_permissions(config: NexusConfig) -> PermissionAuditReport:
    """Audit metadata only; never open file contents or change permissions."""
    return PermissionAuditReport(
        private_data=_scan_scope(config.data_path.expanduser()),
        inbox=_scan_scope(config.inbox_path.expanduser()),
    )


__all__ = ["PermissionAuditReport", "audit_permissions"]
