"""Synthetic rollback canary with Git metadata outside the temporary worktree."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .errors import GitRollbackDrillError

_CANARY_FILES = 6


@dataclass(frozen=True, slots=True)
class GitRollbackDrillReport:
    files: int
    metadata_external: bool
    worktree_git_entry_absent: bool
    mutation_detected: bool
    rollback_hashes_match: bool
    clean_after_rollback: bool
    private_permissions: bool
    cleanup_verified: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": all(
                (
                    self.metadata_external,
                    self.worktree_git_entry_absent,
                    self.mutation_detected,
                    self.rollback_hashes_match,
                    self.clean_after_rollback,
                    self.private_permissions,
                    self.cleanup_verified,
                )
            ),
            "mode": "synthetic-temporary",
            "files": self.files,
            "metadata_external": self.metadata_external,
            "worktree_git_entry_absent": self.worktree_git_entry_absent,
            "mutation_detected": self.mutation_detected,
            "rollback_point_created": True,
            "rollback_hashes_match": self.rollback_hashes_match,
            "clean_after_rollback": self.clean_after_rollback,
            "private_permissions": self.private_permissions,
            "cleanup_verified": self.cleanup_verified,
            "production_paths_accessed": False,
            "production_writes": False,
            "temporary_writes": True,
        }


def _git_environment(drill_root: Path) -> dict[str, str]:
    path_value = os.environ.get("PATH", "")
    return {
        "PATH": path_value,
        "HOME": str(drill_root),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TEMPLATE_DIR": str(drill_root / "empty-git-template"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "NEXUS Synthetic Drill",
        "GIT_AUTHOR_EMAIL": "nexus-drill@example.invalid",
        "GIT_COMMITTER_NAME": "NEXUS Synthetic Drill",
        "GIT_COMMITTER_EMAIL": "nexus-drill@example.invalid",
        "GIT_AUTHOR_DATE": "2026-09-17T09:00:00+03:00",
        "GIT_COMMITTER_DATE": "2026-09-17T09:00:00+03:00",
    }


def _run_git(
    git_executable: str,
    git_dir: Path,
    worktree: Path,
    drill_root: Path,
    *arguments: str,
) -> str:
    try:
        result = subprocess.run(
            [
                git_executable,
                f"--git-dir={git_dir}",
                f"--work-tree={worktree}",
                *arguments,
            ],
            cwd=worktree,
            env=_git_environment(drill_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitRollbackDrillError("synthetic Git command could not run") from exc
    if result.returncode != 0:
        raise GitRollbackDrillError("synthetic Git command failed")
    return result.stdout.strip()


def _create_canary(worktree: Path) -> Path:
    canary = worktree / "Nexus" / "Canary"
    canary.mkdir(mode=0o700, parents=True)
    for index in range(_CANARY_FILES):
        target = canary / f"record-{index + 1}.md"
        target.write_text(
            f"# Synthetic NEXUS rollback canary {index + 1}\n\nvalue: baseline-{index + 1}\n",
            encoding="utf-8",
        )
        os.chmod(target, 0o600)
    return canary


def _manifest(canary: Path) -> dict[str, str]:
    if canary.is_symlink() or not canary.is_dir():
        raise GitRollbackDrillError("synthetic canary root must be a real directory")
    result: dict[str, str] = {}
    for path in sorted(canary.iterdir()):
        if path.is_symlink() or not path.is_file():
            raise GitRollbackDrillError("synthetic canary contains an unsafe entry")
        result[path.name] = sha256(path.read_bytes()).hexdigest()
    return result


def _mutate_canary(canary: Path) -> None:
    changed = canary / "record-1.md"
    changed.write_text("synthetic mutation\n", encoding="utf-8")
    (canary / "record-2.md").unlink()
    added = canary / "untracked.md"
    added.write_text("synthetic untracked mutation\n", encoding="utf-8")
    os.chmod(changed, 0o600)
    os.chmod(added, 0o600)


def _harden_tree(root: Path) -> None:
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink() or not current_path.is_dir():
            raise GitRollbackDrillError("synthetic rollback tree contains an unsafe directory")
        os.chmod(current_path, 0o700)
        for name in directory_names:
            child = current_path / name
            if child.is_symlink() or not child.is_dir():
                raise GitRollbackDrillError(
                    "synthetic rollback tree contains an unsafe directory"
                )
        for name in file_names:
            child = current_path / name
            if child.is_symlink() or not child.is_file():
                raise GitRollbackDrillError("synthetic rollback tree contains an unsafe file")
            os.chmod(child, 0o600)


def _private_permissions(root: Path) -> bool:
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path.stat(follow_symlinks=False).st_mode & 0o077:
            return False
        for name in directory_names:
            child = current_path / name
            if child.is_symlink() or child.stat(follow_symlinks=False).st_mode & 0o077:
                return False
        for name in file_names:
            child = current_path / name
            if child.is_symlink() or child.stat(follow_symlinks=False).st_mode & 0o177:
                return False
    return True


def run_synthetic_git_rollback_drill(
    *, temp_parent: Path | None = None
) -> GitRollbackDrillReport:
    """Create and roll back a six-file canary without reading production paths."""
    if temp_parent is not None and (
        temp_parent.is_symlink() or not temp_parent.is_dir()
    ):
        raise GitRollbackDrillError("temporary parent must be a real directory")
    git_executable = shutil.which("git")
    if git_executable is None:
        raise GitRollbackDrillError("Git executable is unavailable")

    drill_root: Path | None = None
    with tempfile.TemporaryDirectory(
        prefix="nexus-git-rollback-drill-", dir=temp_parent
    ) as directory:
        drill_root = Path(directory)
        os.chmod(drill_root, 0o700)
        worktree = drill_root / "vault-worktree"
        git_dir = drill_root / "git-metadata"
        (drill_root / "empty-git-template").mkdir(mode=0o700)
        worktree.mkdir(mode=0o700)
        canary = _create_canary(worktree)
        baseline_manifest = _manifest(canary)

        _run_git(git_executable, git_dir, worktree, drill_root, "init", "--quiet")
        _run_git(
            git_executable,
            git_dir,
            worktree,
            drill_root,
            "add",
            "--all",
            "--",
            "Nexus/Canary",
        )
        _run_git(
            git_executable,
            git_dir,
            worktree,
            drill_root,
            "commit",
            "--quiet",
            "-m",
            "synthetic rollback baseline",
        )
        rollback_point = _run_git(
            git_executable, git_dir, worktree, drill_root, "rev-parse", "HEAD"
        )
        if len(rollback_point) != 40:
            raise GitRollbackDrillError("synthetic rollback point is invalid")

        metadata_external = not git_dir.is_relative_to(worktree)
        worktree_git_entry = worktree / ".git"
        worktree_git_entry_absent = (
            not worktree_git_entry.exists() and not worktree_git_entry.is_symlink()
        )
        if not metadata_external or not worktree_git_entry_absent:
            raise GitRollbackDrillError("Git metadata crossed the synthetic worktree boundary")

        _mutate_canary(canary)
        mutation_detected = bool(
            _run_git(git_executable, git_dir, worktree, drill_root, "status", "--porcelain")
        )
        if not mutation_detected:
            raise GitRollbackDrillError("synthetic mutation was not detected")

        (canary / "untracked.md").unlink()
        _run_git(
            git_executable,
            git_dir,
            worktree,
            drill_root,
            "restore",
            f"--source={rollback_point}",
            "--staged",
            "--worktree",
            "--",
            "Nexus/Canary",
        )
        restored_manifest = _manifest(canary)
        rollback_hashes_match = baseline_manifest == restored_manifest
        clean_after_rollback = not bool(
            _run_git(git_executable, git_dir, worktree, drill_root, "status", "--porcelain")
        )
        if not rollback_hashes_match or not clean_after_rollback:
            raise GitRollbackDrillError("synthetic Git rollback parity failed")

        _harden_tree(drill_root)
        private_permissions = _private_permissions(drill_root)
        if not private_permissions:
            raise GitRollbackDrillError("synthetic rollback data is not private")
        files = len(restored_manifest)

    cleanup_verified = drill_root is not None and not drill_root.exists()
    if not cleanup_verified:
        raise GitRollbackDrillError("synthetic rollback cleanup could not be verified")
    return GitRollbackDrillReport(
        files=files,
        metadata_external=True,
        worktree_git_entry_absent=True,
        mutation_detected=True,
        rollback_hashes_match=True,
        clean_after_rollback=True,
        private_permissions=True,
        cleanup_verified=True,
    )


__all__ = ["GitRollbackDrillReport", "run_synthetic_git_rollback_drill"]
