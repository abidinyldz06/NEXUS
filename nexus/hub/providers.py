"""Explicit, read-only provider usage snapshots. No inference or secret persistence."""

from __future__ import annotations

import http.client
import json
import math
from datetime import datetime, timezone
from typing import Any, Callable

_PROVIDERS = {"openrouter", "gemini", "nvidia", "antigravity"}
_FIELDS = (
    "usage", "usage_daily", "usage_weekly", "usage_monthly", "limit", "limit_remaining",
)
_MAX_RESPONSE = 32768


class ProviderUsageError(ValueError):
    """Unsupported provider request."""


def _credentials(provider: str) -> dict[str, Any]:
    # The general host resolver can migrate/persist credential pools during a
    # read. Use its scoped secret seam and read-only config, never pool mutation.
    from agent.secret_scope import get_secret
    from hermes_cli.config import load_config_readonly

    model = (load_config_readonly() or {}).get("model", {})
    name = "OPENROUTER_API_KEY"
    if isinstance(model, dict) and model.get("provider") == provider:
        pointer = model.get("key_env") or model.get("api_key_env")
        if isinstance(pointer, str) and pointer.strip():
            name = pointer.strip()
    return {"api_key": get_secret(name) or (
        get_secret("OPENROUTER_API_KEY") if name != "OPENROUTER_API_KEY" else None
    )}


def _read_key(key: str) -> tuple[int, Any]:
    # Fixed TLS origin/path: custom inference URLs, proxies and redirects cannot
    # receive this credential. No automatic retry; no response/error body logging.
    connection = http.client.HTTPSConnection("openrouter.ai", timeout=8)
    try:
        connection.request("GET", "/api/v1/key", headers={
            "Authorization": "Bearer " + key, "Accept": "application/json",
        })
        response = connection.getresponse()
        if response.status != 200:
            return response.status, None
        raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            raise ValueError("response exceeds limit")
        return response.status, json.loads(raw)
    finally:
        connection.close()


def snapshot(
    provider: str,
    *,
    resolve: Callable[[str], dict[str, Any]] = _credentials,
    transport: Callable[[str], tuple[int, Any]] = _read_key,
) -> dict[str, Any]:
    """Whitelist metrics, retaining missing values as unknown (never zero)."""
    if provider not in _PROVIDERS:
        raise ProviderUsageError("sağlayıcı desteklenmiyor")
    result: dict[str, Any] = {
        "provider": provider, "status": "unavailable", "metrics": None,
        "checked_at": None, "source": None, "scope": "current_key",
        "inference_called": False,
    }
    if provider != "openrouter":
        result["scope"] = "project" if provider == "gemini" else "unverified"
        result["reason"] = {
            "gemini": "Kota proje bazlıdır; AI Studio üzerinden kontrol edin.",
            "nvidia": "Kullanım/kota okuma bağlantısı henüz doğrulanmadı. Nemotron 3 Super seçilebilir; fiyat doğrulanmadan çağrı yok.",
            "antigravity": "Uygulama abonelik kotası model API kotasından ayrıdır.",
        }[provider]
        return result
    try:
        key = resolve(provider).get("api_key")
    except Exception:
        result.update(status="credentials_unavailable", reason="Hermes bağlantısı okunamadı.")
        return result
    if not key:
        result.update(status="not_configured", reason="OpenRouter anahtarı Hermes'te tanımlı değil.")
        return result
    if not isinstance(key, str) or not key.isascii() or any(ord(c) < 33 for c in key):
        result.update(status="credentials_unavailable", reason="Hermes anahtarı kullanılamıyor.")
        return result
    try:
        status, payload = transport(key)
        if status != 200:
            code = (
                "unauthorized" if status in (401, 403)
                else "rate_limited" if status == 429 else "unavailable"
            )
            result.update(status=code, reason="Sağlayıcı kullanım bilgisi alınamadı.")
            return result
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise ValueError("invalid response")
        if data.get("is_management_key") is True or data.get("is_provisioning_key") is True:
            result.update(
                status="unsupported_key",
                reason="Yönetim anahtarı yerine sınırlı model anahtarı kullanın.",
            )
            return result
        metrics = {field: _number(data.get(field)) for field in _FIELDS}
        reset = data.get("limit_reset")
        result.update(
            status="available" if any(v is not None for v in metrics.values()) else "unknown",
            metrics=metrics, currency="USD", source="provider_api",
            checked_at=datetime.now(timezone.utc).isoformat(),
            limit_reset=reset if reset in ("daily", "weekly", "monthly") else None,
            reason="Yalnız bu anahtarın kullanımı/limiti; hesap bakiyesi veya görev bütçesi değildir.",
        )
    except Exception:
        result.update(status="unavailable", reason="Sağlayıcı yanıtı güvenle okunamadı.")
    return result


def _number(value: Any) -> int | float | None:
    if type(value) not in (int, float):
        return None
    try:
        return value if math.isfinite(value) and value >= 0 else None
    except OverflowError:
        return None
