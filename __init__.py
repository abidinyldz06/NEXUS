"""Hermes plugin entry point for NEXUS."""

from __future__ import annotations

from typing import Any

from .nexus.cli import configure_parser, run_command


def register(ctx: Any) -> None:
    """Register the NEXUS v0.1 CLI and tool-free extraction route."""
    ctx.register_auxiliary_task(
        "nexus_extract",
        display_name="NEXUS memory extraction",
        description="Extract provenance-backed memory candidates from untrusted text.",
    )

    def setup_fn(parser: Any) -> None:
        configure_parser(parser, handler_fn)

    def handler_fn(args: Any) -> int:
        return run_command(args, ctx)

    ctx.register_cli_command(
        name="nexus",
        help="Inspect and manage the NEXUS memory foundation",
        description="Local-first review, search and output-only reminders for NEXUS v0.1.",
        setup_fn=setup_fn,
        handler_fn=handler_fn,
    )


__all__ = ["register"]
