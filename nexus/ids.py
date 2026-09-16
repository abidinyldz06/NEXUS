"""Stable, opaque identifiers for NEXUS records."""

from __future__ import annotations

import re
import uuid
from enum import StrEnum


class IdPrefix(StrEnum):
    SOURCE = "src"
    MEMORY = "mem"
    ENTITY = "ent"
    RELATION = "rel"
    COMMITMENT = "com"
    REVIEW = "rev"
    RUN = "run"


_ID_RE = re.compile(r"^(src|mem|ent|rel|com|rev|run)_[0-9a-f]{32}$")


def new_id(prefix: IdPrefix) -> str:
    """Return an immutable, non-semantic record identifier."""
    if not isinstance(prefix, IdPrefix):
        raise TypeError("prefix must be an IdPrefix")
    return f"{prefix.value}_{uuid.uuid4().hex}"


def is_nexus_id(value: object, expected: IdPrefix | None = None) -> bool:
    """Return whether *value* is a valid NEXUS id, optionally of one kind."""
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        return False
    return expected is None or value.startswith(f"{expected.value}_")
