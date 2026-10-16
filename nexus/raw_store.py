"""Safe Inbox discovery and content-addressed private raw storage."""

from __future__ import annotations

import os
import stat as stat_module
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import UnsafeSourceError, VaultError
from .fingerprints import sha256_bytes
from .vault.paths import resolve_safe_vault_path

SUPPORTED_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".txt", ".html", ".htm"})
DEFAULT_MAX_SOURCE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    path: Path
    relative_path: str
    size_bytes: int
    mtime_ns: int
    content_sha256: str
    suffix: str


@dataclass(frozen=True, slots=True)
class RejectedSource:
    relative_path: str
    reason: str


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    accepted: tuple[DiscoveredSource, ...]
    rejected: tuple[RejectedSource, ...]


def _read_regular_file(path: Path, *, max_bytes: int | None = None) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat_module.S_ISREG(before.st_mode):
            raise UnsafeSourceError("source is not a regular file")
        if max_bytes is not None and before.st_size > max_bytes:
            raise UnsafeSourceError("source exceeds the configured size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise UnsafeSourceError("source exceeds the configured size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise UnsafeSourceError("source changed during read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def read_discovered(source: DiscoveredSource) -> bytes:
    """Reopen a discovered file without following links and verify its snapshot."""
    try:
        payload, current = _read_regular_file(source.path, max_bytes=source.size_bytes)
    except OSError as exc:
        raise UnsafeSourceError("source is unreadable or became a symlink") from exc
    if (
        current.st_size != source.size_bytes
        or current.st_mtime_ns != source.mtime_ns
        or sha256_bytes(payload) != source.content_sha256
    ):
        raise UnsafeSourceError("source changed after discovery")
    return payload


def _destination_hash(path: Path) -> str:
    try:
        payload, _ = _read_regular_file(path)
    except OSError as exc:
        raise UnsafeSourceError("raw destination is unreadable or unsafe") from exc
    return sha256_bytes(payload)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _relative_display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _looks_like_expected_format(suffix: str, prefix: bytes) -> bool:
    stripped = prefix.lstrip().lower()
    if suffix == ".json":
        return stripped.startswith((b"{", b"["))
    if suffix == ".jsonl":
        return stripped.startswith(b"{")
    if suffix in {".html", ".htm"}:
        return b"<html" in stripped or b"<!doctype html" in stripped
    return True


def discover_inbox(
    inbox_path: Path,
    *,
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    stable_seconds: int = 5,
    now: float | None = None,
) -> DiscoveryReport:
    """Discover supported regular files without following symlinks or writing."""
    if max_source_bytes <= 0 or stable_seconds < 0:
        raise ValueError("discovery limits must be non-negative")
    root = inbox_path.expanduser()
    if not root.exists():
        return DiscoveryReport((), (RejectedSource(".", "inbox_missing"),))
    if root.is_symlink() or not root.is_dir():
        raise UnsafeSourceError("inbox_path must be a real directory, not a symlink")
    root_resolved = root.resolve(strict=True)
    current_time = time.time() if now is None else now
    accepted: list[DiscoveredSource] = []
    rejected: list[RejectedSource] = []

    for directory, dirnames, filenames in os.walk(root_resolved, followlinks=False):
        directory_path = Path(directory)
        safe_dirs: list[str] = []
        for name in sorted(dirnames):
            candidate = directory_path / name
            if candidate.is_symlink():
                rejected.append(
                    RejectedSource(_relative_display(candidate, root_resolved), "symlink_rejected")
                )
            else:
                safe_dirs.append(name)
        dirnames[:] = safe_dirs

        for name in sorted(filenames):
            candidate = directory_path / name
            relative = _relative_display(candidate, root_resolved)
            try:
                if candidate.is_symlink():
                    rejected.append(RejectedSource(relative, "symlink_rejected"))
                    continue
                try:
                    resolved = resolve_safe_vault_path(root_resolved, candidate)
                except VaultError:
                    rejected.append(RejectedSource(relative, "path_escape"))
                    continue
                if not _inside(resolved, root_resolved):
                    rejected.append(RejectedSource(relative, "path_escape"))
                    continue
                stat = candidate.stat(follow_symlinks=False)
                if not stat_module.S_ISREG(stat.st_mode):
                    rejected.append(RejectedSource(relative, "not_regular_file"))
                    continue
                suffix = candidate.suffix.lower()
                if suffix not in SUPPORTED_SUFFIXES:
                    rejected.append(RejectedSource(relative, "unsupported_extension"))
                    continue
                if stat.st_size > max_source_bytes:
                    rejected.append(RejectedSource(relative, "oversize"))
                    continue
                if current_time - stat.st_mtime < stable_seconds:
                    rejected.append(RejectedSource(relative, "not_stable"))
                    continue
                payload, after = _read_regular_file(candidate, max_bytes=max_source_bytes)
                if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ino,
                ):
                    rejected.append(RejectedSource(relative, "changed_during_read"))
                    continue
                if not _looks_like_expected_format(suffix, payload[:4096]):
                    rejected.append(RejectedSource(relative, "format_mismatch"))
                    continue
                accepted.append(
                    DiscoveredSource(
                        path=resolved,
                        relative_path=relative,
                        size_bytes=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                        content_sha256=sha256_bytes(payload),
                        suffix=suffix,
                    )
                )
            except (OSError, UnsafeSourceError, ValueError):
                rejected.append(RejectedSource(relative, "unreadable"))
    return DiscoveryReport(tuple(accepted), tuple(rejected))


class RawStore:
    """Content-addressed raw/quarantine store outside the canonical Vault."""

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path.expanduser()
        if not self.data_path.is_absolute() or self.data_path.is_symlink():
            raise UnsafeSourceError("data_path must be an absolute non-symlink path")

    def archive(self, source: DiscoveredSource) -> Path:
        return self._copy_verified(source, self.data_path / "raw")

    def quarantine(self, source: DiscoveredSource) -> Path:
        return self._copy_verified(source, self.data_path / "quarantine")

    def _copy_verified(self, source: DiscoveredSource, destination_root: Path) -> Path:
        payload = read_discovered(source)

        destination_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination_root.is_symlink():
            raise UnsafeSourceError("raw destination must not be a symlink")
        os.chmod(destination_root, 0o700)
        bucket = destination_root / source.content_sha256[:2]
        bucket.mkdir(mode=0o700, exist_ok=True)
        os.chmod(bucket, 0o700)
        destination = bucket / f"{source.content_sha256}{source.suffix}"
        if destination.exists():
            if destination.is_symlink() or _destination_hash(destination) != source.content_sha256:
                raise UnsafeSourceError("raw destination collision or tampering detected")
            return destination

        with tempfile.NamedTemporaryFile(dir=bucket, prefix=".nexus-", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
            try:
                os.link(temp_path, destination, follow_symlinks=False)
            except FileExistsError:
                destination_is_safe = (
                    not destination.is_symlink()
                    and _destination_hash(destination) == source.content_sha256
                )
                if not destination_is_safe:
                    raise UnsafeSourceError("raw destination collision or tampering detected")
        finally:
            if temp_path.exists():
                temp_path.unlink()
        os.chmod(destination, 0o600)
        return destination
