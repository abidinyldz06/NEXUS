"""Explicit, fixed synthetic free-model test; no Vault content or task dispatch."""

from __future__ import annotations

import stat
import time
from pathlib import Path
from uuid import UUID

from . import free_model, providers
from .budget import BudgetError, PilotBudget

PROMPT = "This is a synthetic connectivity test. Reply exactly NEXUS_FREE_OK."


def run(config, *, request_id: str, model: str) -> dict:
    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BudgetError("işlem kimliği geçersiz") from exc
    if model not in free_model.SELECTED_MODELS:
        raise BudgetError("model ücretsiz izin listesinde değil")
    if config.auto_publish_enabled:
        raise BudgetError("pilot otomatik yayın kapalıyken kullanılabilir")
    # Preflight before any ledger write or model POST. Always use fixed content.
    catalog = free_model.read_catalog()
    free_model.build_request(PROMPT, data_class="synthetic", external_authorized=True,
                             model=model, catalog=catalog)
    key = providers._credentials("openrouter").get("api_key")
    if (not isinstance(key, str) or not key.startswith("sk-or-") or not key.isascii()
            or any(ord(c) < 33 for c in key)):
        raise BudgetError("OpenRouter anahtarı Hermes'te kullanılamıyor")
    data = Path(config.data_path)
    if (not data.is_absolute() or not data.is_dir() or data.is_symlink()
            or any(parent.is_symlink() for parent in data.parents)
            or stat.S_IMODE(data.stat().st_mode) & 0o077):
        raise BudgetError("mevcut özel NEXUS veri dizini gerekli")
    folder = data / "hub"
    if folder.is_symlink():
        raise BudgetError("pilot dizini güvenli değil")
    if folder.exists() and (not folder.is_dir() or stat.S_IMODE(folder.stat().st_mode) & 0o077):
        raise BudgetError("pilot dizini yalnız kullanıcıya açık olmalı")
    folder.mkdir(mode=0o700, exist_ok=True)
    ledger = PilotBudget(folder / "free-pilot.sqlite3", per_job_usd="0",
                         daily_usd="0", monthly_usd="0")
    hold = ledger.reserve(request_id, ceiling_usd="0")
    if not hold["created"]:
        return {"status": "already_recorded", "hold_status": hold["status"],
                "inference_attempted": False, "retry": False}
    started = False

    def transport(secret, body):
        nonlocal started
        started = True
        return free_model._transport(secret, body)

    start = time.monotonic()
    try:
        result = free_model.complete_free(
            PROMPT, key=key, data_class="synthetic", external_authorized=True,
            model=model, transport=transport, catalog_reader=lambda: catalog,
        )
    except Exception:
        ledger.reconcile(request_id, verified_cost_usd=None if started else "0")
        raise BudgetError("pilot sonucu doğrulanamadı; otomatik tekrar yapılmaz") from None
    verified = result.get("cost_verified") is True
    state = ledger.reconcile(request_id, verified_cost_usd="0" if verified else None)
    # Return only evidence; provider output, prompt, key and raw errors stay out.
    return {"status": result["status"], "requested_model": model,
            "expected_output": result.get("output", "").strip() == "NEXUS_FREE_OK",
            "cost_verified": verified, "cost_usd": 0 if verified else None,
            "hold_status": state["status"], "inference_attempted": started,
            "http_status": result.get("http_status"),
            "elapsed_seconds": round(time.monotonic() - start, 2), "retry": False}
