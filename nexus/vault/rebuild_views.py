"""Generated current-state views for canonical records."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..contracts import Memory, RecordStatus
from .renderer import render_safe_pre
from .repository import VaultRepository
from .transaction import VaultWrite


@dataclass(frozen=True, slots=True)
class MemoryViewEntry:
    record_id: str
    summary: str
    status: str
    relative_path: Path


def render_memory_view_entries(entries: Iterable[MemoryViewEntry]) -> str:
    active = sorted(
        (entry for entry in entries if entry.status == RecordStatus.ACTIVE.value),
        key=lambda entry: entry.record_id,
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
    for entry in active:
        target = entry.relative_path.relative_to("Nexus").with_suffix("")
        lines.extend(
            [
                f"- [[../{target.as_posix()}|{entry.record_id}]]",
                f"  {render_safe_pre(entry.summary)}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_current_memory_view(memories: Iterable[Memory], repository: VaultRepository) -> str:
    return render_memory_view_entries(
        MemoryViewEntry(
            record_id=memory.id,
            summary=memory.summary,
            status=memory.status.value,
            relative_path=repository.record_path(memory),
        )
        for memory in memories
    )


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
