"""Explicit supersession rules for canonical memory corrections."""

from __future__ import annotations

from dataclasses import replace

from .contracts import Memory, RecordStatus
from .errors import VaultError


def apply_memory_correction(previous: Memory, replacement: Memory) -> tuple[Memory, Memory]:
    """Return linked old/new records without deleting historical memory."""
    if previous.id == replacement.id:
        raise VaultError("a correction must create a new memory id")
    if previous.status is not RecordStatus.ACTIVE or previous.superseded_by is not None:
        raise VaultError("only one active memory can be superseded")
    if replacement.status is not RecordStatus.ACTIVE or replacement.superseded_by is not None:
        raise VaultError("replacement memory must start active")
    if previous.id not in replacement.supersedes:
        raise VaultError("replacement memory must name the previous id in supersedes")
    if any(item != previous.id for item in replacement.supersedes):
        raise VaultError("Phase 5 correction supports one explicit predecessor")
    superseded = replace(
        previous,
        status=RecordStatus.SUPERSEDED,
        superseded_by=replacement.id,
    )
    return superseded, replacement
