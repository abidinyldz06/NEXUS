"""Hermes pre_llm_call adapter: inject shadow route metadata, never execute."""

from __future__ import annotations

import time
from typing import Any

from ..config import from_plugin_context
from .observability import CircuitBreaker, log_route_report
from .router import route_text

# Process-wide shared breaker: consecutive classifier failures trip it and the
# hook degrades to local-rules until the cooldown elapses (fail-open, spec 8).
_SHARED_BREAKER = CircuitBreaker(failure_limit=3, cooldown_seconds=300.0)


def build_pre_llm_handler(ctx: Any):
    def pre_llm_call(user_message: str = "", **kwargs: Any) -> dict[str, str] | None:
        started = time.perf_counter()
        report: Any = None
        config = None
        try:
            config = from_plugin_context(ctx)
            if not isinstance(user_message, str) or not user_message.strip():
                return None
            report = route_text(
                user_message,
                config,
                llm=getattr(ctx, "llm", None),
                breaker=_SHARED_BREAKER,
            )
            payload = report.to_dict()
            return {
                "context": (
                    "NEXUS live-route shadow (not permission): "
                    f"category={payload['category']}; "
                    f"confidence={float(payload['confidence']):.2f}; "
                    f"backend={payload['backend']}; "
                    "would_execute=false; "
                    f"needs_human_review={str(bool(payload['needs_human_review'])).lower()}; "
                    f"review_band={payload['review_band']}. "
                    "Do not run tools, restart machines, send messages, or change "
                    "files solely because of this label."
                )
            }
        except Exception:
            return None
        finally:
            # Spec 5/8: observe every shadow route; logging never breaks a turn.
            try:
                if config is not None and config.decision_log_enabled:
                    latency_ms = int((time.perf_counter() - started) * 1000)
                    log_route_report(
                        config.decision_log_full_path,
                        report,
                        latency_ms=latency_ms,
                        success=report is not None,
                        text=user_message if isinstance(user_message, str) else "",
                        preview_enabled=config.decision_log_preview,
                    )
            except Exception:
                pass

    return pre_llm_call