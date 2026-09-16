"""Common source adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..contracts import SourceType
from ..normalize import NormalizedConversation


@dataclass(frozen=True, slots=True)
class ParsedSource:
    source_type: SourceType
    adapter_name: str
    adapter_version: str
    original_name: str
    conversations: tuple[NormalizedConversation, ...]

    @property
    def message_count(self) -> int:
        return sum(len(item.messages) for item in self.conversations)


class SourceAdapter(Protocol):
    name: str
    version: str
    source_type: SourceType

    def parse_bytes(self, payload: bytes, *, original_name: str) -> ParsedSource: ...

    def supports(self, path: Path, payload_prefix: bytes) -> bool: ...
