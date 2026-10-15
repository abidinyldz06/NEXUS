"""Bounded Hub views over the existing canonical Vault and private stores."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

from ..config import NexusConfig
from ..contracts import ReviewItem, ReviewStatus
from ..errors import NexusIndexError, ReviewStoreError, VaultError
from ..ids import IdPrefix, is_nexus_id
from ..index import IndexStore, search_index
from ..review.store import ReviewStore
from ..vault import extract_record_payload


def _preview(item: ReviewItem) -> str:
    candidate = item.candidate
    for field in ("summary", "statement", "display_name", "predicate", "literal"):
        value = candidate.get(field)
        if isinstance(value, str) and value.strip():
            return value[:240]
    return "Önizleme yok"


def _source_refs(payload: dict[str, Any]) -> list[dict[str, str]]:
    refs = payload.get("source_refs")
    if not isinstance(refs, list):
        return []
    return [
        {
            "source_id": item["source_id"],
            "excerpt": item.get("excerpt", ""),
        }
        for item in refs[:10]
        if isinstance(item, dict)
        and isinstance(item.get("source_id"), str)
        and isinstance(item.get("excerpt", ""), str)
    ]


def overview(config: NexusConfig) -> dict[str, Any]:
    """Report available data without rebuilding the index or creating a store."""
    index: dict[str, Any] = {"ready": False, "records": 0, "updated_at": None}
    try:
        with IndexStore(config.index_path, read_only=True) as store:
            store.require_current_search_profile()
            index["records"] = store.counts()[0]
            index["updated_at"] = datetime.fromtimestamp(
                config.index_path.stat().st_mtime, UTC
            ).isoformat()
            index["ready"] = True
    except (NexusIndexError, OSError):
        index["message"] = "Arama indeksi hazır değil"

    review: dict[str, Any] = {"ready": False, "pending": 0}
    try:
        review["pending"] = len(ReviewStore(config.data_path).list(status=ReviewStatus.PENDING))
        review["ready"] = True
    except ReviewStoreError:
        review["message"] = "İnceleme kuyruğu okunamadı"

    return {
        "index": index,
        "review": review,
        "apps": [
            {"name": "NEXUS / Obsidian", "status": "hazır" if index["ready"] else "erişilemiyor"},
            {"name": "Hermes", "status": "panel bağlı"},
            {"name": "Model sağlayıcıları", "status": "Hermes kullanım kayıtları isteğe bağlı görüntülenir"},
            {"name": "Antigravity", "status": "Uygulama kotası Hermes model kullanımından ayrıdır"},
        ],
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
    }


def search(config: NexusConfig, query: str, *, limit: int = 20) -> dict[str, Any]:
    items = search_index(config.index_path, query, limit=limit)
    return {
        "items": [
            {
                "id": item.record_id,
                "kind": item.kind,
                "status": item.status,
                "title": item.title,
                "snippet": item.snippet,
                "relative_path": item.relative_path,
            }
            for item in items
        ],
        "read_only": True,
    }


def record(config: NexusConfig, record_id: str) -> dict[str, Any]:
    if not is_nexus_id(record_id):
        raise NexusIndexError("geçersiz kayıt kimliği")
    if config.vault_path is None or config.vault_path.is_symlink():
        raise NexusIndexError("Obsidian kasası erişilebilir değil")
    with IndexStore(config.index_path, read_only=True) as store:
        store.require_current_search_profile()
        row = store.connection.execute(
            "SELECT kind, status, title, relative_path, content_sha256 FROM records WHERE id = ?",
            (record_id,),
        ).fetchone()
    if row is None:
        raise NexusIndexError("kayıt bulunamadı")

    relative = PurePosixPath(row["relative_path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise NexusIndexError("kayıt yolu güvenli değil")
    path = config.vault_path
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise NexusIndexError("kayıt yolu güvenli değil")
    if not path.is_file():
        raise NexusIndexError("kaynak kayıt bulunamadı")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise NexusIndexError("kaynak kayıt okunamadı") from exc
    if sha256(content).hexdigest() != row["content_sha256"]:
        raise NexusIndexError("indeks ve kaynak kayıt uyuşmuyor")
    try:
        payload = extract_record_payload(content.decode("utf-8"))
    except (UnicodeError, VaultError) as exc:
        raise NexusIndexError("kaynak kayıt okunamadı") from exc
    if payload.get("id") != record_id:
        raise NexusIndexError("indeks ve kaynak kimliği uyuşmuyor")
    return {
        "id": record_id,
        "kind": row["kind"],
        "status": row["status"],
        "title": row["title"],
        "relative_path": row["relative_path"],
        "excerpt": _preview_record(payload),
        "source_refs": _source_refs(payload),
        "canonical_verified": True,
        "original_source_verified": False,
        "read_only": True,
    }


def _preview_record(payload: dict[str, Any]) -> str:
    for field in ("summary", "display_name", "predicate", "literal", "original_name"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value[:500]
    return "Önizleme yok"


def pending_reviews(config: NexusConfig, *, limit: int = 20) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ReviewStoreError("inceleme limiti 1–100 arasında olmalı")
    items = ReviewStore(config.data_path).list(status=ReviewStatus.PENDING)
    return {
        "total": len(items),
        "items": [
            {
                "id": item.id,
                "kind": item.candidate_kind,
                "preview": _preview(item),
                "reason_codes": list(item.reason_codes),
            }
            for item in items[:limit]
        ],
        "read_only": True,
    }


def review_detail(config: NexusConfig, review_id: str) -> dict[str, Any]:
    if not is_nexus_id(review_id, IdPrefix.REVIEW):
        raise ReviewStoreError("geçersiz inceleme kimliği")
    item = ReviewStore(config.data_path).get(review_id)
    return {
        "id": item.id,
        "kind": item.candidate_kind,
        "status": item.status.value,
        "preview": _preview(item),
        "reason_codes": list(item.reason_codes),
        "source_refs": _source_refs(
            {"source_refs": [
                {"source_id": ref.source_id, "excerpt": ref.excerpt}
                for ref in item.source_refs
            ]}
        ),
        "read_only": True,
    }
