"""Deterministic fingerprints used across ingestion stages."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Iterable

from .contracts import SourceType
from .normalize import NormalizedMessage, normalize_text


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def source_lineage_key(
    source_type: SourceType, external_id: str | None, content_sha256: str
) -> str:
    identity = external_id.strip() if external_id and external_id.strip() else content_sha256
    return stable_hash([source_type.value, identity])


def fallback_message_id(
    *, source_identity: str, role: str, created_at: str | None, content_sha256: str
) -> str:
    return f"msg_{stable_hash([source_identity, role, created_at, content_sha256])[:32]}"


def segment_fingerprint(messages: Iterable[NormalizedMessage], *, version: str) -> str:
    return stable_hash(
        [version, [[item.message_id, item.content_sha256] for item in messages]]
    )


def memory_fingerprint(
    *, kind: str, statement: str, entity_ids: Iterable[str], effective_date: str | None
) -> str:
    return stable_hash(
        [kind, normalize_text(statement).casefold(), sorted(entity_ids), effective_date]
    )
