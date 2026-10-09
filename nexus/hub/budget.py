"""Durable pilot budget holds; no provider dispatch or content persistence.

A hold is not permission to call a model. A future dispatcher must additionally
verify credentials, prices, token bounds and policy, and dispatch only once.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from uuid import UUID

_GENERATION_ID = re.compile(r"^gen-[A-Za-z0-9_-]{8,80}$")
_MODEL_NAME = re.compile(r"^[A-Za-z0-9_.:/+-]{1,200}$")
_DIAGNOSTIC_CLASSES = frozenset({
    "http_rejected", "timeout", "invalid_output", "invalid_response",
    "unverified_cost", "verified_zero",
})


class BudgetError(ValueError):
    """A budget operation was rejected without dispatching work."""


def _blocking_hold_clause() -> str:
    """Unknown cost keeps the ledger closed, including an accepted empty hold."""
    return (
        "status IN ('reserved', 'unknown', 'overrun') "
        "OR (status = 'accepted' AND actual IS NULL)"
    )


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


def _generation_id(value: str) -> str:
    if not isinstance(value, str) or _GENERATION_ID.fullmatch(value) is None:
        raise BudgetError("generation kimliği geçersiz")
    return value


def _model_name(value: str) -> str:
    if not isinstance(value, str) or _MODEL_NAME.fullmatch(value) is None:
        raise BudgetError("model kaydı geçersiz")
    return value


def _http_status(value: object) -> int | None:
    """A real HTTP status only. Booleans and missing values stay unknown."""
    if type(value) is not int or not 100 <= value <= 599:
        return None
    return value


def _diagnostic_class(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _DIAGNOSTIC_CLASSES:
        raise BudgetError("hata sınıfı geçersiz")
    return value


class PilotBudget:
    """Immutable explicit pilot caps, serialized holds, one unresolved flight.

    The caller supplies an existing private directory. No production path is
    selected implicitly. Caps cannot be increased by reopening the same ledger.
    Uncertain requests retain their full hold, even across calendar rollover.
    """

    def __init__(self, path: Path, *, per_job_usd: str, daily_usd: str, monthly_usd: str):
        self.path = path
        self.caps = tuple(_money(v) for v in (per_job_usd, daily_usd, monthly_usd))
        if self.caps != (0, 0, 0) and not 0 < self.caps[0] <= self.caps[1] <= self.caps[2]:
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
        if not (ceiling == 0 and self.caps == (0, 0, 0)) and not 0 < ceiling <= self.caps[0]:
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
                "SELECT 1 FROM holds WHERE " + _blocking_hold_clause() + " LIMIT 1"
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
            if old_status == "accepted":
                raise BudgetError("bırakılmış belirsiz kayıt sıfırlanmış gibi kapatılamaz")
            if old_status in ("settled", "overrun"):
                if old_actual != actual:
                    raise BudgetError("uzlaştırılmış harcama değiştirilemez")
                return {"status": old_status, "dispatch_enabled": False}
            status = "unknown" if actual is None else "overrun" if actual > ceiling else "settled"
            connection.execute(
                "UPDATE holds SET status=?, actual=? WHERE id=?", (status, actual, request_id)
            )
            return {"status": status, "dispatch_enabled": False}

    def accept_unknown(self, request_id: str) -> dict:
        """Record that the cost is still unknown. This does not open a new job."""
        request_id = _identifier(request_id)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT status, actual FROM holds WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise BudgetError("rezervasyon bulunamadı")
            status, actual = row
            if status == "accepted" and actual is None:
                return {"status": "accepted", "cost_verified": False, "dispatch_enabled": False}
            if status != "unknown" or actual is not None:
                raise BudgetError("yalnız tutarı boş belirsiz kayıt bırakılabilir")
            connection.execute("UPDATE holds SET status='accepted' WHERE id=?", (request_id,))
            return {"status": "accepted", "cost_verified": False, "dispatch_enabled": False}

    def hold(self, request_id: str) -> tuple[str, int | None] | None:
        """Read one hold. A missing ledger is not created."""
        request_id = _identifier(request_id)
        if not self.path.is_file():
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT status, actual FROM holds WHERE id=?", (request_id,)
            ).fetchone()
            connection.rollback()
            return None if row is None else (row[0], row[1])

    def generation_ref(self, request_id: str) -> str | None:
        """Return the stored provider id, or None. Does not create the table."""
        request_id = _identifier(request_id)
        if not self.path.is_file():
            return None
        with closing(self._connect()) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generation_refs'"
            ).fetchone()
            row = connection.execute(
                "SELECT generation_id FROM generation_refs WHERE id=?", (request_id,)
            ).fetchone() if exists else None
            connection.rollback()
            return None if row is None else row[0]

    def record_generation_id(self, request_id: str, generation_id: str, *, source: str) -> None:
        """Store the provider id only. Prompt and output never belong here."""
        request_id = _identifier(request_id)
        generation_id = _generation_id(generation_id)
        if source not in {"response", "evidence"}:
            raise BudgetError("generation kaydı kaynağı geçersiz")
        with closing(self._connect()) as connection, connection:
            if not connection.execute("SELECT 1 FROM holds WHERE id=?", (request_id,)).fetchone():
                raise BudgetError("rezervasyon bulunamadı")
            self._ensure_generation_refs(connection)
            stored = connection.execute(
                "SELECT generation_id FROM generation_refs WHERE id=?", (request_id,)
            ).fetchone()
            if stored:
                if stored[0] != generation_id:
                    raise BudgetError("kayıtlı generation kimliği değiştirilemez")
                return
            try:
                connection.execute(
                    "INSERT INTO generation_refs VALUES (?, ?, ?, ?)",
                    (request_id, generation_id, source, datetime.now(UTC).isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise BudgetError("bu generation kimliği başka bir kayda bağlı") from exc

    def settle_from_evidence(
        self, request_id: str, *, verified_cost_usd: str, generation_id: str, source: str,
    ) -> dict:
        """Settle only with a numeric provider cost and its generation id.

        An accepted empty hold can move here. ``reconcile`` still refuses to
        close that hold, including with an unverified zero. Unknown stays
        unknown unless this call supplies a representable cost.
        """
        request_id = _identifier(request_id)
        generation_id = _generation_id(generation_id)
        if source not in {"response", "evidence"}:
            raise BudgetError("generation kaydı kaynağı geçersiz")
        actual = _money(verified_cost_usd)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT ceiling, status, actual FROM holds WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise BudgetError("rezervasyon bulunamadı")
            ceiling, old_status, old_actual = row
            self._ensure_generation_refs(connection)
            stored = connection.execute(
                "SELECT generation_id FROM generation_refs WHERE id=?", (request_id,)
            ).fetchone()
            if stored and stored[0] != generation_id:
                raise BudgetError("kayıtlı generation kimliği değiştirilemez")
            if old_status in ("settled", "overrun"):
                if old_actual != actual:
                    raise BudgetError("uzlaştırılmış harcama değiştirilemez")
                if not stored:
                    self._insert_generation_ref(connection, request_id, generation_id, source)
                return {"status": old_status, "cost_verified": True, "changed": False,
                        "confirmed_now": True, "dispatch_enabled": False}
            if old_status not in ("unknown", "accepted") or old_actual is not None:
                raise BudgetError("bu kayıt sağlayıcı kanıtıyla kapatılamaz")
            status = "overrun" if actual > ceiling else "settled"
            connection.execute(
                "UPDATE holds SET status=?, actual=? WHERE id=? AND status=? AND actual IS NULL",
                (status, actual, request_id, old_status),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise BudgetError("bu kayıt sağlayıcı kanıtıyla kapatılamaz")
            if not stored:
                self._insert_generation_ref(connection, request_id, generation_id, source)
            return {"status": status, "cost_verified": True, "changed": True,
                    "confirmed_now": True, "dispatch_enabled": False}

    @staticmethod
    def _insert_generation_ref(connection: sqlite3.Connection, request_id: str,
                               generation_id: str, source: str) -> None:
        try:
            connection.execute(
                "INSERT INTO generation_refs VALUES (?, ?, ?, ?)",
                (request_id, generation_id, source, datetime.now(UTC).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise BudgetError("bu generation kimliği başka bir kayda bağlı") from exc

    @staticmethod
    def _ensure_generation_refs(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS generation_refs ("
            "id TEXT PRIMARY KEY, generation_id TEXT NOT NULL UNIQUE, "
            "source TEXT NOT NULL CHECK (source IN ('response', 'evidence')), "
            "recorded_at TEXT NOT NULL)"
        )

    def begin_diagnostic(self, request_id: str, *, model: str) -> None:
        """Open one content-free attempt. An existing attempt is not replaced."""
        request_id = _identifier(request_id)
        model = _model_name(model)
        with closing(self._connect()) as connection, connection:
            if not connection.execute("SELECT 1 FROM holds WHERE id=?", (request_id,)).fetchone():
                raise BudgetError("rezervasyon bulunamadı")
            self._ensure_diagnostics(connection)
            try:
                connection.execute(
                    "INSERT INTO diagnostics (id, model, started_at, finished_at, phase, "
                    "http_status, error_class) VALUES (?, ?, ?, NULL, 'running', NULL, NULL)",
                    (request_id, model, datetime.now(UTC).isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise BudgetError("ilk teşhis kaydı değiştirilemez") from exc
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise BudgetError("ilk teşhis kaydı değiştirilemez")

    def finish_diagnostic(
        self, request_id: str, *, phase: str, http_status: object,
        error_class: object, verified_cost_usd: str | None,
    ) -> dict:
        """Close the open attempt and settle its cost in one transaction.

        A finished attempt is left untouched. If this write fails, the cost is
        not recorded as zero and the call is not a success.
        """
        request_id = _identifier(request_id)
        if phase not in {"draft_result", "failed", "unknown"}:
            raise BudgetError("işlem durumu geçersiz")
        klass = _diagnostic_class(error_class)
        code = _http_status(http_status)
        actual = None if verified_cost_usd is None else _money(verified_cost_usd)
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT ceiling, status, actual FROM holds WHERE id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise BudgetError("rezervasyon bulunamadı")
            ceiling, old_status, old_actual = row
            if old_status == "accepted":
                raise BudgetError("bırakılmış belirsiz kayıt sıfırlanmış gibi kapatılamaz")
            if old_status in ("settled", "overrun"):
                if old_actual != actual:
                    raise BudgetError("uzlaştırılmış harcama değiştirilemez")
                raise BudgetError("kapanmış teşhis yeni denemeyle değiştirilemez")
            new_status = "unknown" if actual is None else "overrun" if actual > ceiling else "settled"
            connection.execute(
                "UPDATE holds SET status=?, actual=? WHERE id=? AND status=?",
                (new_status, actual, request_id, old_status),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise BudgetError("teşhis kaydı kapanamadı")
            self._ensure_diagnostics(connection)
            connection.execute(
                "UPDATE diagnostics SET finished_at=?, phase=?, http_status=?, error_class=? "
                "WHERE id=? AND finished_at IS NULL AND phase='running'",
                (datetime.now(UTC).isoformat(), phase, code, klass, request_id),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise BudgetError("ilk teşhis kaydı değiştirilemez")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outcomes "
                "(id TEXT PRIMARY KEY, phase TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO outcomes VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET phase=excluded.phase, updated_at=excluded.updated_at",
                (request_id, phase, datetime.now(UTC).isoformat()),
            )
            return {"status": new_status, "dispatch_enabled": False}

    @staticmethod
    def _ensure_diagnostics(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS diagnostics ("
            "id TEXT PRIMARY KEY, model TEXT NOT NULL, started_at TEXT NOT NULL, "
            "finished_at TEXT, phase TEXT NOT NULL, http_status INTEGER, error_class TEXT, "
            "CHECK (phase IN ('running', 'draft_result', 'failed', 'unknown')), "
            "CHECK (http_status IS NULL OR (http_status >= 100 AND http_status <= 599)), "
            "CHECK (error_class IS NULL OR error_class IN ("
            "'http_rejected', 'timeout', 'invalid_output', 'invalid_response', "
            "'unverified_cost', 'verified_zero')))"
        )

    def record_outcome(self, request_id: str, phase: str) -> None:
        """Only metadata from an explicit invocation; never save prompt or output."""
        request_id = _identifier(request_id)
        if phase not in {"running", "draft_result", "failed", "unknown"}:
            raise BudgetError("işlem durumu geçersiz")
        with closing(self._connect()) as connection, connection:
            if not connection.execute("SELECT 1 FROM holds WHERE id=?", (request_id,)).fetchone():
                raise BudgetError("rezervasyon bulunamadı")
            connection.execute("CREATE TABLE IF NOT EXISTS outcomes "
                               "(id TEXT PRIMARY KEY, phase TEXT NOT NULL, updated_at TEXT NOT NULL)")
            connection.execute("INSERT INTO outcomes VALUES (?, ?, ?) "
                               "ON CONFLICT(id) DO UPDATE SET phase=excluded.phase, updated_at=excluded.updated_at",
                               (request_id, phase, datetime.now(UTC).isoformat()))
