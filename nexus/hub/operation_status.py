"""Read existing cost/outcome metadata only; no creation, migration or dispatch."""
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from . import pilot
from .budget import BudgetError, _blocking_hold_clause


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
            query = ("SELECT h.id, h.status, h.actual, h.day, o.phase, o.updated_at FROM holds h "
                     "LEFT JOIN outcomes o ON o.id=h.id" if has_outcomes else
                     "SELECT id, status, actual, day, NULL, NULL FROM holds")
            ordering = " ORDER BY COALESCE(o.updated_at, h.day) DESC, h.id DESC LIMIT 30" if has_outcomes else " ORDER BY day DESC, id DESC LIMIT 30"
            rows = connection.execute(query + ordering).fetchall()
    except sqlite3.Error:
        raise BudgetError("işlem kayıtları okunamadı; başarı varsayılmadı") from None
    items = []
    for identifier, hold, actual, day, phase, updated in rows:
        active = hold == "reserved" and pilot.is_active(path, identifier)
        state = ("running" if active else "accepted"
                 if hold == "accepted" and actual is None else "draft_result"
                 if phase == "draft_result" and hold == "settled" else "failed"
                 if phase == "failed" and hold == "settled" else "unknown")
        items.append({"id": identifier, "state": state, "hold_status": hold,
                      "cost_verified": actual is not None, "day": day,
                      "updated_at": updated, "output_saved": False, "retry": False})
    return {"items": items, "total": total, "blocked": blocked, "read_only": True}
