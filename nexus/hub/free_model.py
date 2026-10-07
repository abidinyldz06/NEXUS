"""Narrow free-only OpenRouter pilot. No tools, paid fallback or storage."""

from __future__ import annotations

import http.client
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from .budget import BudgetError, validate_pilot_scope

FREE_MODEL = "nvidia/nemotron-3.5-lightning:free"
SELECTED_MODELS = frozenset({
    "stealth/space-bunny-alpha",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "poolside/laguna-s-2.1:free",
    "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3.5-lightning:free",
})


def read_catalog() -> dict[str, Any]:
    """Fresh public model prices; no credential, disk cache or inference."""
    connection = http.client.HTTPSConnection("openrouter.ai", timeout=8)
    try:
        connection.request("GET", "/api/v1/models", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise BudgetError("model kataloğu okunamadı")
        raw = response.read(2097153)
        if len(raw) > 2097152:
            raise BudgetError("model kataloğu boyut sınırını aşıyor")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise BudgetError("model kataloğu geçersiz")
        return payload
    finally:
        connection.close()


def public_price_block(model: str, catalog: dict[str, Any] | None) -> str:
    """Refuse a call. A public zero price is not an NVIDIA invoice."""
    rows = catalog.get("data") if isinstance(catalog, dict) else None
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == model] \
        if isinstance(rows, list) else []
    if len(matches) != 1:
        return "NVIDIA Nemotron 3 Super katalogda doğrulanamadı; çağrı yok"
    pricing = matches[0].get("pricing")
    if not isinstance(pricing, dict) or not {"prompt", "completion"}.issubset(pricing):
        return "NVIDIA Nemotron 3 Super fiyatı katalogda yok; çağrı yok"
    amounts: list[Decimal] = []
    for value in pricing.values():
        try:
            if type(value) not in (str, int, float):
                return "NVIDIA Nemotron 3 Super fiyatı okunamadı; çağrı yok"
            amount = Decimal(str(value))
            if not amount.is_finite() or amount < 0:
                return "NVIDIA Nemotron 3 Super fiyatı okunamadı; çağrı yok"
        except InvalidOperation:
            return "NVIDIA Nemotron 3 Super fiyatı okunamadı; çağrı yok"
        amounts.append(amount)
    if any(amount != 0 for amount in amounts):
        return "NVIDIA Nemotron 3 Super OpenRouter kataloğunda sıfır fiyatlı değil; NVIDIA çağrısı yok"
    return "NVIDIA Nemotron 3 Super katalog fiyatı sıfır görünse de NVIDIA faturası doğrulanmadı; çağrı yok"


def _verify_zero_price(model: str, catalog: dict[str, Any] | None) -> None:
    rows = catalog.get("data") if isinstance(catalog, dict) else None
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == model] \
        if isinstance(rows, list) else []
    if len(matches) != 1:
        raise BudgetError("model güncel katalogda doğrulanamadı")
    pricing = matches[0].get("pricing")
    if not isinstance(pricing, dict) or not {"prompt", "completion"}.issubset(pricing):
        raise BudgetError("model fiyatı bilinmiyor")
    for value in pricing.values():
        try:
            if type(value) not in (str, int, float) or Decimal(str(value)) != 0:
                raise BudgetError("yalnız sıfır fiyatlı modeller kabul edilir")
        except InvalidOperation as exc:
            raise BudgetError("model fiyatı geçersiz") from exc


def build_request(text: str, *, data_class: str, external_authorized: bool,
                  model: str = FREE_MODEL, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_pilot_scope(provider="openrouter", model=model, data_class=data_class,
                         external_authorized=external_authorized)
    if model not in SELECTED_MODELS:
        raise BudgetError("model ücretsiz izin listesinde değil; ücretli fallback yok")
    if model in SELECTED_MODELS:
        _verify_zero_price(model, catalog)
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise BudgetError("pilot metni 1–500 karakter olmalı")
    return {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "stream": False,
        "max_tokens": 64,
        "provider": {
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
            "max_price": {"prompt": 0, "completion": 0, "request": 0, "image": 0},
        },
    }


def _transport(key: str, body: dict[str, Any]) -> tuple[int, Any]:
    connection = http.client.HTTPSConnection("openrouter.ai", timeout=20)
    try:
        connection.request("POST", "/api/v1/chat/completions", body=json.dumps(body),
                           headers={"Authorization": "Bearer " + key,
                                    "Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return response.status, None
        raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError("oversized response")
        return response.status, json.loads(raw)
    finally:
        connection.close()


def complete_free(
    text: str, *, key: str, data_class: str, external_authorized: bool,
    model: str = FREE_MODEL,
    transport: Callable[[str, dict[str, Any]], tuple[int, Any]] = _transport,
    catalog_reader: Callable[[], dict[str, Any]] = read_catalog,
) -> dict[str, Any]:
    # Build every field ourselves. No caller-controlled extra_body, model lists,
    # tools, plugins, URL or fallback settings can widen the request.
    # Reject policy/model/content before even the public catalog request.
    validate_pilot_scope(provider="openrouter", model=model, data_class=data_class,
                         external_authorized=external_authorized)
    if model not in SELECTED_MODELS:
        raise BudgetError("model ücretsiz izin listesinde değil")
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise BudgetError("pilot metni 1–500 karakter olmalı")
    if (not isinstance(key, str) or not key.startswith("sk-or-")
            or not key.isascii() or any(ord(c) < 33 for c in key)):
        raise BudgetError("OpenRouter anahtarı kullanılamıyor")
    catalog = None
    if model in SELECTED_MODELS:
        try:
            catalog = catalog_reader()
        except Exception:
            return {"status": "stopped", "reason": "güncel ücretsiz fiyat doğrulanamadı",
                    "cost_verified": False, "retry": False}
    body = build_request(text, data_class=data_class,
                         external_authorized=external_authorized, model=model, catalog=catalog)
    try:
        status, payload = transport(key, body)
        if status != 200:
            return {"status": "stopped", "reason": "ücretsiz rota yanıt vermedi",
                    "http_status": status, "cost_verified": False, "retry": False}
        if not isinstance(payload, dict):
            raise ValueError("invalid response")
        usage = payload.get("usage")
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if type(cost) not in (int, float) or cost != 0:
            return {"status": "needs_reconciliation", "cost_verified": False, "retry": False}
        try:
            chosen = payload.get("model")
            choices = payload.get("choices")
            content = choices[0]["message"]["content"]
            if (not isinstance(chosen, str) or len(chosen) > 200
                    or not isinstance(content, str) or len(content) > 4000):
                raise ValueError("invalid output")
        except Exception:
            # Cost was already numeric zero. A bad output must not look like an unknown charge.
            return {"status": "stopped", "reason": "yanıt metni doğrulanamadı",
                    "cost_verified": True, "cost_usd": 0, "retry": False}
        return {"status": "completed", "model": chosen, "output": content,
                "cost_verified": True, "cost_usd": 0, "retry": False}
    except Exception:
        # No raw HTTP/SDK error or potentially credential-bearing content.
        return {"status": "unknown", "reason": "yanıt güvenle doğrulanamadı",
                "cost_verified": False, "retry": False}
