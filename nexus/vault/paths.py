"""Contain every vault-relative path inside its base directory."""

from __future__ import annotations

from pathlib import Path

from ..errors import VaultError


def resolve_safe_vault_path(base_dir: Path, target_path: str | Path) -> Path:
    """Resolve ``target_path`` and reject anything outside ``base_dir``.

    ``..`` segments and symlink escapes fail closed. The returned path is absolute.
    """
    base = Path(base_dir).expanduser()
    if not base.is_absolute():
        raise VaultError("vault base must be absolute")
    base_resolved = base.resolve()
    raw = Path(target_path)
    if any(part in {"", ".."} for part in raw.parts):
        raise VaultError("path escapes the vault root")
    candidate = raw if raw.is_absolute() else base / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise VaultError("path escapes the vault root")
    return resolved
