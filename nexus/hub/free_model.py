"""Narrow free-only OpenRouter pilot. No tools, paid fallback or storage."""

from __future__ import annotations

import http.client
import json
from typing import Any, Callable

from .budget import BudgetError, validate_pilot_scope

FREE_MODEL = "openrouter/free"


def build_request(text: str, *, data_class: str, external_authorized: bool,
                  model: str = FREE_MODEL) -> dict[str, Any]:
    validate_pilot_scope(provider="openrouter", model=model, data_class=data_class,
                         external_authorized=external_authorized)
    if model != FREE_MODEL:
        raise BudgetError("ilk pilot yalnız openrouter/free kullanır; ücretli fallback yok")
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise BudgetError("pilot metni 1–500 karakter olmalı")
    return {
        "model": FREE_MODEL,
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
) -> dict[str, Any]:
    # Build every field ourselves. No caller-controlled extra_body, model lists,
    # tools, plugins, URL or fallback settings can widen the request.
    body = build_request(text, data_class=data_class,
                         external_authorized=external_authorized, model=model)
    if (not isinstance(key, str) or not key.startswith("sk-or-")
            or not key.isascii() or any(ord(c) < 33 for c in key)):
        raise BudgetError("OpenRouter anahtarı kullanılamıyor")
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
        chosen = payload.get("model")
        if not isinstance(chosen, str) or len(chosen) > 200:
            raise ValueError("invalid model evidence")
        choices = payload.get("choices")
        content = choices[0]["message"]["content"]
        if not isinstance(content, str) or len(content) > 4000:
            raise ValueError("invalid output")
        return {"status": "completed", "model": chosen, "output": content,
                "cost_verified": True, "cost_usd": 0, "retry": False}
    except Exception:
        # No raw HTTP/SDK error or potentially credential-bearing content.
        return {"status": "unknown", "reason": "yanıt güvenle doğrulanamadı",
                "cost_verified": False, "retry": False}
