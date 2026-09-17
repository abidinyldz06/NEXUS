"""Generated current-state views for canonical records."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..contracts import Memory, RecordStatus
from .renderer import render_safe_pre
from .repository import VaultRepository
from .transaction import VaultWrite


def render_current_memory_view(memories: Iterable[Memory], repository: VaultRepository) -> str:
    active = sorted(
        (memory for memory in memories if memory.status is RecordStatus.ACTIVE),
        key=lambda memory: memory.id,
    )
    lines = [
        "---",
        "managed_by: nexus",
        "generated: true",
        "---",
        "",
        "# Current Memory",
        "",
        "This view is generated from active canonical records.",
        "",
    ]
    for memory in active:
        target = repository.record_path(memory).relative_to("Nexus")
        lines.extend(
            [
                f"- [[../{target.with_suffix('').as_posix()}|{memory.id}]]",
                f"  {render_safe_pre(memory.summary)}",
            ]
        )
    return "\n".join(lines) + "\n"


def current_memory_view_write(
    memories: Iterable[Memory],
    repository: VaultRepository,
    *,
    expected_sha256: str | None = None,
) -> VaultWrite:
    return VaultWrite(
        Path("Nexus/Views/Current-Memory.md"),
        render_current_memory_view(memories, repository).encode("utf-8"),
        expected_sha256,
    )
