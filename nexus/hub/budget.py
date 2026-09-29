"""Durable pilot budget holds; no provider dispatch or content persistence.

A hold is not permission to call a model. A future dispatcher must additionally
verify credentials, prices, token bounds and policy, and dispatch only once.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from uuid import UUID


class BudgetError(ValueError):
    """A budget operation was rejected without dispatching work."""


def validate_pilot_scope(
    *, provider: str, model: str, data_class: str, external_authorized: bool,
) -> None:
    """Validate explicit scope, not inspect content or grant execution permission."""
    if provider not in {"openrouter", "gemini", "nvidia"}:
        raise BudgetError("bu sağlayıcı ilk API pilotunda desteklenmiyor")
    if not isinstance(model, str) or not model.strip() or len(model) > 200:
        raise BudgetError("model açıkça seçilmeli")
    if data_class not in {"synthetic", "selected_external"} or external_authorized is not True:
        raise BudgetError("yalnız açıkça izinli sentetik veya seçili içerik kullanılabilir")


def _money(value: str) -> int:
    if not isinstance(value, str) or len(value) > 32:
        raise BudgetError("USD tutarı ondalık metin olmalı")
    try:
        number = Decimal(value)
        if not number.is_finite() or not 0 <= number <= 1000:
            raise BudgetError("USD tutarı 0–1000 aralığında olmalı")
        with localcontext() as context:
            context.prec = 64  # Do not round sub-micro-dollar values into accepted amounts.
            scaled = number * 1_000_000
        if scaled != scaled.to_integral_value():
            raise BudgetError("USD tutarı en fazla altı ondalık basamak içerebilir")
        return int(scaled)
    except InvalidOperation as exc:
        raise BudgetError("USD tutarı geçersiz") from exc


def _identifier(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BudgetError("işlem kimliği geçersiz") from exc


class PilotBudget:
    """Immutable explicit pilot caps, serialized holds, one unresolved flight.

    The caller supplies an existing private directory. No production path is
    selected implicitly. Caps cannot be increased by reopening the same ledger.
    Uncertain requests retain their full hold, even across calendar rollover.
    """

    def __init__(self, path: Path, *, per_job_usd: str, daily_usd: str, monthly_usd: str):
        self.path = path
        self.caps = tuple(_money(v) for v in (per_job_usd, daily_usd, monthly_usd))
        if not 0 < self.caps[0] <= self.caps[1] <= self.caps[2]:
            raise BudgetError("iş/gün/ay bütçeleri pozitif ve sıralı olmalı")

    def _connect(self) -> sqlite3.Connection:
        path = self.path
        if not path.is_absolute() or not path.parent.is_dir():
            raise BudgetError("mevcut özel bütçe dizini gerekli")
        if any(parent.is_symlink() for parent in (path.parent, *path.parent.parents)):
            raise BudgetError("bütçe dizininde symlink desteklenmiyor")
        if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
            raise BudgetError("bütçe dizini yalnız kullanıcıya açık olmalı")
        if not path.exists() and not path.is_symlink():
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                pass
        if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise BudgetError("bütçe dosyası güvenli değil")
        connection = sqlite3.connect(path, timeout=5)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS caps "
                "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "per_job INTEGER NOT NULL, daily INTEGER NOT NULL, monthly INTEGER NOT NULL)"
            )
            connection.execute("INSERT OR IGNORE INTO caps VALUES (1, ?, ?, ?)", self.caps)
            stored = connection.execute("SELECT per_job, daily, monthly FROM caps").fetchone()
            if tuple(stored) != self.caps:
                raise BudgetError("kayıtlı bütçe farklı; otomatik değiştirilemez")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS holds (id TEXT PRIMARY KEY, ceiling INTEGER NOT NULL, "
                "day TEXT NOT NULL, month TEXT NOT NULL, status TEXT NOT NULL, actual INTEGER)"
            )
            return connection
        except Exception:
            connection.rollback()
            connection.close()
            raise

    def reserve(self, request_id: str, *, ceiling_usd: str, now: datetime | None = None) -> dict:
        request_id = _identifier(request_id)
        ceiling = _money(ceiling_usd)
        if not 0 < ceiling <= self.caps[0]:
            raise BudgetError("iş rezervasyonu bütçe sınırını aşıyor")
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise BudgetError("bütçe zamanı saat dilimi içermeli")
        day = now.astimezone(UTC).date().isoformat()
        month = day[:7]
        with closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT ceiling, status FROM holds WHERE id=?", (request_id,)
            ).fetchone()
            if existing:
                if existing[0] != ceiling:
                    raise BudgetError("aynı işlem kimliği farklı rezervasyonla kullanılamaz")
                return {"created": False, "status": existing[1], "dispatch_enabled": False}
            if connection.execute(
                "SELECT 1 FROM holds WHERE status IN ('reserved', 'unknown', 'overrun') LIMIT 1"
            ).fetchone():
                raise BudgetError("önceki istek uzlaştırılmadan yeni iş başlayamaz")
            daily = connection.execute(
                "SELECT COALESCE(SUM(actual), 0) FROM holds WHERE day=?", (day,)
            ).fetchone()[0]
            monthly = connection.execute(
                "SELECT COALESCE(SUM(actual), 0) FROM holds WHERE month=?", (month,)
            ).fetchone()[0]
            if daily + ceiling > self.caps[1] or monthly + ceiling > self.caps[2]:
                raise BudgetError("günlük veya aylık bütçe yetersiz")
            connection.execute(
                "INSERT INTO holds VALUES (?, ?, ?, ?, 'reserved', NULL)",
                (request_id, ceiling, day, month),
            )
            return {"created": True, "status": "reserved", "dispatch_enabled": False}

    def reconcile(self, request_id: str, *, verified_cost_usd: str | None) -> dict:
        """Only provider-verified cost settles a hold; unknown is never zero.

        Reconciliation is idempotent. Conflicting settled costs are rejected.
        A verified overrun is recorded honestly and blocks further work.
        """
        request_id = _identifier(request_id)
        actual = None if verified_cost_usd is None else _money(verified_cost_usd)
        if not self.path.exists():
            raise BudgetError("rezervasyon bulunamadı")
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT ceiling, status, actual FROM holds WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise BudgetError("rezervasyon bulunamadı")
            ceiling, old_status, old_actual = row
            if old_status in ("settled", "overrun"):
                if old_actual != actual:
                    raise BudgetError("uzlaştırılmış harcama değiştirilemez")
                return {"status": old_status, "dispatch_enabled": False}
            status = "unknown" if actual is None else "overrun" if actual > ceiling else "settled"
            connection.execute(
                "UPDATE holds SET status=?, actual=? WHERE id=?", (status, actual, request_id)
            )
            return {"status": status, "dispatch_enabled": False}
