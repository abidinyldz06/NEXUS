# ADR 0001: Extend Hermes; do not patch its core

Status: accepted for v0.1

NEXUS will be a standalone user plugin. It will reuse Hermes plugin CLI,
plugin-owned auxiliary LLM tasks, official session export, cron and gateway
delivery. The active `~/.hermes/hermes-agent` vendor tree remains unchanged.

This keeps Hermes updates independent, minimizes tool-schema footprint and gives
NEXUS an explicit rollback boundary.
