"""Hermes pre_llm_call adapter: inject shadow route metadata, never execute."""

from __future__ import annotations

from typing import Any

from ..config import from_plugin_context
from .router import route_text


def build_pre_llm_handler(ctx: Any):
    def pre_llm_call(user_message: str = "", **kwargs: Any) -> dict[str, str] | None:
        try:
            if not isinstance(user_message, str) or not user_message.strip():
                return None
            report = route_text(
                user_message,
                from_plugin_context(ctx),
                llm=getattr(ctx, "llm", None),
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

    return pre_llm_call
