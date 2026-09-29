"""Conservative, local-only suggestions for Hub requests; never dispatch work."""

from __future__ import annotations

import re
import unicodedata


class RouteAdviceError(ValueError):
    """The request cannot safely be classified."""


_DATA_CLASSES = {"undetermined", "local_only", "selected_external", "sensitive"}
_RISK = re.compile(
    r"\b(?:sil\w*|delete\w*|paylas\w*|gonder\w*|yayinla\w*|"
    r"birles\w*|merge\w*|deploy\w*|push\w*|ode\w*|odeme\w*|"
    r"satin\s+al\w*|yukle\w*|upload\w*|anahtar\w*|token\w*)\b"
)
_GITHUB = re.compile(r"\b(?:github|pull\s+request|pr\s*#?\d+)\b")
_MEMORY = re.compile(r"\b(?:hafiza\w*|konusma\w*|sohbet\w*|obsidian|vault|notlar\w*)\b")
_MEMORY_ACTION = re.compile(r"\b(?:bul\w*|ara\w*|hatirla\w*|neydi|goster\w*|karar\w*)\b")
_REMINDER = re.compile(r"\b(?:hatirlat\w*|animsat\w*|alarm\w*|bildir\w*)\b")
_SUMMARY = re.compile(r"\b(?:ozet\w*|kisalt\w*|kisa\s+anlat\w*)\b")
_TASK = re.compile(r"\b(?:gorev\w*|arastir\w*|taslak\w*|planla\w*)\b")
_STATUS = re.compile(r"\b(?:durum\w*|status|kontrol\w*|bak\w*|goster\w*|listele\w*)\b")


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold().replace("ı", "i"))
    return "".join(char for char in folded if not unicodedata.combining(char))


def advise(request_text: str, *, data_class: str = "undetermined") -> dict[str, object]:
    """Return a bounded suggestion with no persistence, tool call, or model invocation."""
    if not isinstance(request_text, str) or not request_text.strip() or len(request_text) > 500:
        raise RouteAdviceError("istek 1–500 karakter olmalı")
    if not isinstance(data_class, str) or data_class not in _DATA_CLASSES:
        raise RouteAdviceError("veri kapsamı desteklenmiyor")

    text = _normalize(request_text)
    github = bool(_GITHUB.search(text))
    memory = bool(_MEMORY.search(text) and _MEMORY_ACTION.search(text))
    reminder = bool(_REMINDER.search(text))
    summary = bool(_SUMMARY.search(text))
    task = bool(_TASK.search(text))
    github_status = github and bool(_STATUS.search(text))
    risky = bool(_RISK.search(text))

    # Multiple intentions should not be collapsed into a silently chosen action.
    matches = [github_status, memory and not github, reminder, summary, task]
    if sum(matches) > 1 and not risky:
        return _result("unclear", None, None, "needs_clarification",
                       "Birden fazla amaç var; önce tek bir iş seçin.")
    if risky:
        target = "GitHub" if github else "NEXUS" if memory else "Hermes" if reminder else None
        return _result(
            "external_action", target, None, "requires_review",
            "Dış etkili veya hassas bir işlem olabilir; "
            "kapsam ve izin insan tarafından incelenmeli.",
        )
    if data_class == "sensitive" and (summary or task):
        return _result(
            "sensitive_request", None, None, "requires_review",
            "Hassas içerik dış modele yönlendirilemez; yerel yol ayrıca doğrulanmalı.",
        )
    if github_status:
        return _result(
            "status_lookup", "GitHub", "none", "suggested",
            "GitHub durumuna salt okunur bakış önerilir; bağlantı henüz çalıştırılmaz.",
        )
    if memory and not github:
        return _result("memory_search", "NEXUS", "none", "suggested",
                       "Önce yerel hafızada kaynaklı arama önerilir; model gerekmez.")
    if reminder:
        return _result("reminder", "Hermes", "none", "requires_review",
                       "Hatırlatma zamanı ve teslim kanalı ayrıca onaylanmalı.")
    if summary:
        role = "local_required" if data_class == "local_only" else "summarizer"
        return _result(
            "summary", "Hermes", role, "suggested",
            "Yalnız açıkça seçilen metin özetlenebilir; "
            "model bağlantısı henüz açılmadı.",
        )
    if task:
        role = "local_required" if data_class == "local_only" else "researcher"
        return _result(
            "task_draft", "Hermes", role, "suggested",
            "Önce çalıştırılmayan görev taslağı önerilir; "
            "hedef ve bütçe ayrıca belirlenmeli.",
        )
    return _result("unclear", None, None, "needs_clarification",
                   "Hedef güvenle belirlenemedi; daha somut tek bir iş yazın.")


def _result(
    intent: str, target_app: str | None, model_role: str | None, status: str, reason: str
) -> dict[str, object]:
    return {
        "intent": intent,
        "target_app": target_app,
        "model_role": model_role,
        "status": status,
        "reason": reason,
        "execution_enabled": False,
        "rule_version": "h3-local-v1",
    }
