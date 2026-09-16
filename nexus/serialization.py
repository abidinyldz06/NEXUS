"""Deterministic JSON serialization for versioned contracts."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any


def to_primitive(value: Any) -> Any:
    """Convert supported domain values to JSON-safe primitives."""
    if is_dataclass(value) and not isinstance(value, type):
        return to_primitive(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_primitive(item) for item in value]
    return value


def dumps(value: Any, *, pretty: bool = False) -> str:
    """Serialize deterministically without leaking Python-specific representations."""
    return json.dumps(
        to_primitive(value),
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )
