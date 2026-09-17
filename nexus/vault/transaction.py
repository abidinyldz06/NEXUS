"""Preconditioned multi-file Vault transaction with in-process rollback."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import VaultConflictError, VaultError, VaultTransactionError
from ..fingerprints import sha256_bytes
from ..ids import IdPrefix, is_nexus_id


@dataclass(frozen=True, slots=True)
class VaultWrite:
    relative_path: Path
    content: bytes
    expected_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionResult:
    run_id: str
    written_paths: tuple[str, ...]
    content_sha256: tuple[str, ...]
    committed_at: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class VaultTransaction:
    """Write only under ``Vault/Nexus`` with optimistic preconditions."""

    def __init__(self, vault_root: Path, *, fault_after_writes: int | None = None) -> None:
        self.vault_root = vault_root
        self.fault_after_writes = fault_after_writes

    def commit(self, writes: tuple[VaultWrite, ...], *, run_id: str) -> TransactionResult:
        if not is_nexus_id(run_id, IdPrefix.RUN):
            raise VaultError("run_id must be a run_ NEXUS id")
        if not writes:
            raise VaultError("Vault transaction requires at least one write")
        root = self._validated_root()
        normalized = tuple(self._validate_write(root, write) for write in writes)
        paths = [write.relative_path.as_posix() for write in normalized]
        if len(paths) != len(set(paths)):
            raise VaultError("Vault transaction contains duplicate target paths")
        self._check_preconditions(root, normalized)

        transactions = root / "Nexus" / ".transactions"
        self._assert_safe_components(root, transactions.relative_to(root))
        transactions.mkdir(mode=0o700, parents=True, exist_ok=True)
        if transactions.is_symlink():
            raise VaultError("Vault transaction directory must not be a symlink")
        stage = transactions / run_id
        if stage.exists() or stage.is_symlink():
            raise VaultConflictError("transaction run_id already exists")
        stage.mkdir(mode=0o700)
        backups = stage / "backups"
        staged = stage / "staged"
        backups.mkdir(mode=0o700)
        staged.mkdir(mode=0o700)

        existing: dict[str, bool] = {}
        manifest_items: list[dict[str, object]] = []
        committed_indexes: list[int] = []
        preserve_stage = False
        try:
            for index, write in enumerate(normalized):
                key = write.relative_path.as_posix()
                target = root / write.relative_path
                existing[key] = target.exists()
                stage_file = staged / f"{index:04d}.tmp"
                self._write_file(stage_file, write.content, mode=0o600)
                old_hash = None
                if target.exists():
                    old_content = self._read_regular(target)
                    old_hash = sha256_bytes(old_content)
                    self._write_file(backups / f"{index:04d}.bak", old_content, mode=0o600)
                manifest_items.append(
                    {
                        "path": key,
                        "old_sha256": old_hash,
                        "new_sha256": sha256_bytes(write.content),
                    }
                )
            self._write_file(
                stage / "manifest.json",
                json.dumps(
                    {
                        "version": 1,
                        "run_id": run_id,
                        "state": "prepared",
                        "items": manifest_items,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
                mode=0o600,
            )

            for index, write in enumerate(normalized):
                target = root / write.relative_path
                self._ensure_target_parent(root, target.parent)
                self._before_replace(index, target)
                self._check_precondition(root, write)
                os.replace(staged / f"{index:04d}.tmp", target)
                committed_indexes.append(index)
                os.chmod(target, 0o600)
                self._fsync_directory(target.parent)
                if self.fault_after_writes == len(committed_indexes):
                    raise OSError("injected Vault transaction failure")

            committed_at = _utc_now()
            audit_path = root / "Nexus" / "Audit" / "Runs" / f"{run_id}.json"
            self._ensure_target_parent(root, audit_path.parent)
            if audit_path.exists() or audit_path.is_symlink():
                raise VaultConflictError("run audit already exists")
            audit_payload = json.dumps(
                {
                    "version": 1,
                    "run_id": run_id,
                    "state": "committed",
                    "committed_at": committed_at,
                    "writes": manifest_items,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            self._atomic_create(audit_path, audit_payload)
            result = TransactionResult(
                run_id=run_id,
                written_paths=tuple(paths),
                content_sha256=tuple(str(item["new_sha256"]) for item in manifest_items),
                committed_at=committed_at,
            )
        except Exception as exc:
            rollback_complete = self._rollback(
                root,
                normalized,
                existing,
                backups,
                committed_indexes,
            )
            message = (
                "Vault transaction failed and was rolled back"
                if rollback_complete
                else "Vault transaction failed and rollback was incomplete"
            )
            preserve_stage = not rollback_complete
            raise VaultTransactionError(message) from exc
        finally:
            if (
                not preserve_stage
                and stage.exists()
                and stage.is_dir()
                and not stage.is_symlink()
            ):
                shutil.rmtree(stage)
        return result

    def _validated_root(self) -> Path:
        root = self.vault_root
        if not root.is_absolute() or not root.exists() or not root.is_dir() or root.is_symlink():
            raise VaultError("vault_root must be an existing absolute non-symlink directory")
        return root

    def _validate_write(self, root: Path, write: VaultWrite) -> VaultWrite:
        path = write.relative_path
        if path.is_absolute() or not path.parts or path.parts[0] != "Nexus":
            raise VaultError("Vault writes must use relative paths below Nexus/")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise VaultError("Vault write path contains an unsafe component")
        if path.parts[1:2] == (".transactions",):
            raise VaultError("callers cannot write transaction internals")
        self._assert_safe_components(root, path)
        if not isinstance(write.content, bytes):
            raise VaultError("Vault write content must be bytes")
        if write.expected_sha256 is not None and (
            len(write.expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in write.expected_sha256)
        ):
            raise VaultError("expected_sha256 must be a lowercase SHA-256 digest")
        return write

    def _assert_safe_components(self, root: Path, relative: Path) -> None:
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise VaultError("Vault path must not traverse symlinks")

    def _check_preconditions(self, root: Path, writes: tuple[VaultWrite, ...]) -> None:
        for write in writes:
            self._check_precondition(root, write)

    def _check_precondition(self, root: Path, write: VaultWrite) -> None:
        target = root / write.relative_path
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise VaultError("Vault target must be a regular non-symlink file")
            if write.expected_sha256 is None:
                raise VaultConflictError("existing Vault file requires an expected hash")
            if sha256_bytes(self._read_regular(target)) != write.expected_sha256:
                raise VaultConflictError("Vault content precondition failed")
        elif target.is_symlink():
            raise VaultError("Vault target must not be a symlink")
        elif write.expected_sha256 is not None:
            raise VaultConflictError("expected Vault file is missing")

    def _before_replace(self, index: int, target: Path) -> None:
        """Test seam invoked immediately before the final precondition check."""

    def _ensure_target_parent(self, root: Path, parent: Path) -> None:
        relative = parent.relative_to(root)
        self._assert_safe_components(root, relative)
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._assert_safe_components(root, relative)

    def _rollback(
        self,
        root: Path,
        writes: tuple[VaultWrite, ...],
        existing: dict[str, bool],
        backups: Path,
        committed_indexes: list[int],
    ) -> bool:
        complete = True
        for index in reversed(committed_indexes):
            write = writes[index]
            key = write.relative_path.as_posix()
            target = root / write.relative_path
            backup = backups / f"{index:04d}.bak"
            try:
                expected_new_hash = sha256_bytes(write.content)
                target_is_ours = (
                    target.exists()
                    and not target.is_symlink()
                    and target.is_file()
                    and sha256_bytes(target.read_bytes()) == expected_new_hash
                )
                if existing.get(key) and backup.exists():
                    if not target_is_ours:
                        complete = False
                        continue
                    self._ensure_target_parent(root, target.parent)
                    os.replace(backup, target)
                    self._fsync_directory(target.parent)
                elif not existing.get(key):
                    if target.is_symlink() or (target.exists() and not target_is_ours):
                        complete = False
                        continue
                    if target_is_ours:
                        target.unlink()
                        self._fsync_directory(target.parent)
            except (OSError, VaultError):
                complete = False
        return complete

    @staticmethod
    def _read_regular(path: Path) -> bytes:
        if path.is_symlink() or not path.is_file():
            raise VaultError("Vault file must be a regular non-symlink file")
        return path.read_bytes()

    @staticmethod
    def _write_file(path: Path, content: bytes, *, mode: int) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _atomic_create(self, target: Path, content: bytes) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".nexus-", dir=target.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            if target.exists() or target.is_symlink():
                raise VaultConflictError("Vault audit target already exists")
            os.replace(temp, target)
            self._fsync_directory(target.parent)
        finally:
            if temp.exists():
                temp.unlink()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
