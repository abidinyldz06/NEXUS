"""Private, non-dispatching Hub task drafts."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ..config import NexusConfig


class TaskDraftError(Exception):
    """A draft could not be safely read or stored."""


def _database_path(config: NexusConfig) -> Path:
    data = config.data_path
    if not data.is_absolute():
        raise TaskDraftError("özel veri dizini mutlak olmalı")
    parent = data / "hub"
    if data.is_symlink() or (data.exists() and not data.is_dir()):
        raise TaskDraftError("özel veri dizini güvenli değil")
    if data.exists() and stat.S_IMODE(data.stat().st_mode) & 0o077:
        raise TaskDraftError("özel veri dizini yalnız kullanıcıya açık olmalı")
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise TaskDraftError("görev dizini güvenli değil")
    if parent.exists() and stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise TaskDraftError("görev dizini yalnız kullanıcıya açık olmalı")
    path = parent / "tasks.sqlite3"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise TaskDraftError("görev veritabanı güvenli değil")
    if path.exists() and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise TaskDraftError("görev veritabanı yalnız kullanıcıya açık olmalı")
    return path


def _validate_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise TaskDraftError(f"{name} 1–{maximum} karakter olmalı")
    return value.strip()


def _payload(fields: dict[str, object]) -> dict[str, str]:
    target = _validate_text(fields.get("target_app"), "hedef uygulama", 40)
    if target not in {"NEXUS", "Hermes", "GitHub", "Diğer"}:
        raise TaskDraftError("hedef uygulama desteklenmiyor")
    return {
        "title": _validate_text(fields.get("title"), "başlık", 160),
        "goal": _validate_text(fields.get("goal"), "amaç", 2000),
        "expected_output": _validate_text(fields.get("expected_output"), "beklenen çıktı", 1000),
        "target_app": target,
    }


def _record(row: sqlite3.Row) -> dict[str, object]:
    fields = json.loads(row["payload_json"])
    return {
        "id": row["id"],
        **fields,
        "status": "draft",
        "data_class": "belirlenmedi",
        "selected_refs": [],
        "permission_scope": "onaylanmadı",
        "model_role": None,
        "time_limit_seconds": None,
        "spend_limit_usd": None,
        "hermes_run_id": None,
        "result_evidence": None,
        "created_at": row["created_at"],
        "updated_at": row["created_at"],
    }


def list_drafts(config: NexusConfig, *, limit: int = 30) -> dict[str, object]:
    """Reading an absent store must not create files or migrate schemas."""
    if not 1 <= limit <= 100:
        raise TaskDraftError("liste limiti 1–100 arasında olmalı")
    path = _database_path(config)
    if not path.exists():
        return {"items": [], "total": 0, "dispatch_enabled": False}
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            total = connection.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
            rows = connection.execute(
                "SELECT id, payload_json, created_at FROM drafts "
                "ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise TaskDraftError("görev taslakları okunamadı") from exc
    try:
        items = [_record(row) for row in rows]
    except (ValueError, TypeError, KeyError) as exc:
        raise TaskDraftError("görev taslakları bozuk") from exc
    return {"items": items, "total": total, "dispatch_enabled": False}


def create_draft(
    config: NexusConfig, fields: dict[str, object], *, idempotency_key: str
) -> dict[str, object]:
    """Persist one draft per key; never submit anything to Hermes."""
    try:
        idempotency_key = str(UUID(idempotency_key))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TaskDraftError("geçersiz işlem kimliği") from exc
    payload = json.dumps(_payload(fields), ensure_ascii=False, sort_keys=True)
    path = _database_path(config)
    data = config.data_path
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    if data.is_symlink() or stat.S_IMODE(data.stat().st_mode) & 0o077:
        raise TaskDraftError("özel veri dizini yalnız kullanıcıya açık olmalı")
    parent = path.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or stat.S_IMODE(parent.stat().st_mode) & 0o077:
        raise TaskDraftError("görev dizini yalnız kullanıcıya açık olmalı")
    if not path.exists():
        try:
            descriptor = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(descriptor)
        except FileExistsError:
            pass  # Another request created the store; SQLite handles the race below.
    if path.is_symlink():
        raise TaskDraftError("görev veritabanı güvenli değil")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise TaskDraftError("görev veritabanı yalnız kullanıcıya açık olmalı")
    try:
        with closing(sqlite3.connect(path, timeout=10)) as connection:
            with connection:
                connection.row_factory = sqlite3.Row
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS drafts ("
                    "id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE, "
                    "payload_json TEXT NOT NULL, created_at TEXT NOT NULL)"
                )
                existing = connection.execute(
                    "SELECT id, payload_json, created_at FROM drafts WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["payload_json"] != payload:
                        raise TaskDraftError(
                            "aynı işlem kimliği farklı bir taslak için kullanıldı"
                        )
                    return {"task": _record(existing), "created": False, "dispatched": False}
                identifier = "task_" + uuid4().hex
                created_at = datetime.now(UTC).isoformat()
                connection.execute(
                    "INSERT INTO drafts (id, idempotency_key, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (identifier, idempotency_key, payload, created_at),
                )
                row = connection.execute(
                    "SELECT id, payload_json, created_at FROM drafts WHERE id = ?", (identifier,)
                ).fetchone()
    except sqlite3.Error as exc:
        raise TaskDraftError("görev taslağı kaydedilemedi") from exc
    return {"task": _record(row), "created": True, "dispatched": False}
