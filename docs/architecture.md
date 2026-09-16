# NEXUS v0.1 architecture baseline

## Boundaries

- Hermes remains the agent/runtime host. NEXUS does not patch Hermes core.
- Obsidian Markdown is canonical human-readable memory.
- SQLite is disposable derived state and must rebuild from canonical records.
- Raw exports stay outside the synced Vault.
- Untrusted source text enters only a tool-free structured extraction call.
- A deterministic policy engine and writer own all side effects.

## Extension footprint

NEXUS follows Hermes's footprint ladder:

1. plugin CLI command;
2. plugin-owned auxiliary LLM task;
3. optional skill after search/review commands exist;
4. fixed cron scripts after local canary;
5. no new core tool in v0.1.

## Current shadow-mode invariant

The current implementation is read-only. `write_enabled` is hard-coded false in
status output. Config validation and ingestion dry-run may inspect sources but
create no production state. Extraction candidates are not published.
