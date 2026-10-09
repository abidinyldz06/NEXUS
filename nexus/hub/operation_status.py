"""Read existing cost/outcome metadata only; no creation, migration or dispatch."""
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from . import pilot
from .budget import BudgetError, _blocking_hold_clause, _generation_id


def snapshot(config) -> dict:
    path = Path(config.data_path) / "hub" / "free-pilot.sqlite3"
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise BudgetError("işlem kayıt yolu güvenli değil")
    for directory in (path.parent, path.parent.parent):
        if directory.exists() and (not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077):
            raise BudgetError("işlem kayıt dizini yalnız kullanıcıya açık olmalı")
    if not path.exists():
        return {"items": [], "total": 0, "blocked": False, "read_only": True}
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise BudgetError("işlem kayıt dosyası güvenli değil")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) FROM holds").fetchone()[0]
            blocked = bool(connection.execute(
                "SELECT 1 FROM holds WHERE " + _blocking_hold_clause() + " LIMIT 1"
            ).fetchone())
            has_outcomes = bool(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outcomes'"
            ).fetchone())
            has_refs = bool(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generation_refs'"
            ).fetchone())
            phase = "o.phase, o.updated_at" if has_outcomes else "NULL, NULL"
            ref = "g.generation_id" if has_refs else "NULL"
            joins = " FROM holds h"
            if has_outcomes:
                joins += " LEFT JOIN outcomes o ON o.id=h.id"
            if has_refs:
                joins += " LEFT JOIN generation_refs g ON g.id=h.id"
            ordering = (" ORDER BY COALESCE(o.updated_at, h.day) DESC, h.id DESC LIMIT 30"
                        if has_outcomes else " ORDER BY h.day DESC, h.id DESC LIMIT 30")
            rows = connection.execute(
                "SELECT h.id, h.status, h.actual, h.day, " + phase + ", " + ref + joins + ordering
            ).fetchall()
    except sqlite3.Error:
        raise BudgetError("işlem kayıtları okunamadı; başarı varsayılmadı") from None
    items = []
    for identifier, hold, actual, day, phase, updated, generation_id in rows:
        active = hold == "reserved" and pilot.is_active(path, identifier)
        state = ("running" if active else "accepted"
                 if hold == "accepted" and actual is None else "draft_result"
                 if phase == "draft_result" and hold == "settled" else "failed"
                 if phase == "failed" and hold == "settled" else "unknown")
        try:
            shown_id = None if generation_id is None else _generation_id(generation_id)
        except BudgetError:
            shown_id = None
        items.append({"id": identifier, "state": state, "hold_status": hold,
                      "cost_verified": actual is not None, "generation_id": shown_id,
                      "day": day, "updated_at": updated, "output_saved": False, "retry": False})
    return {"items": items, "total": total, "blocked": blocked, "read_only": True}
