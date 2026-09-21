# NEXUS v0.1 architecture baseline

## Boundaries

- Hermes remains the agent/runtime host. NEXUS does not patch Hermes core.
- Obsidian Markdown is canonical human-readable memory.
- SQLite is disposable derived state and must rebuild from canonical records.
- Raw exports stay outside the synced Vault.
- Untrusted source text enters only a tool-free structured extraction call.
- A deterministic policy engine and writer own all side effects.

## Live-route DecisionRouter (Phase A)

Live-turn classification is a separate shadow surface from memory extraction.
It must not sit inside ChatGPT/Hermes ingest, segmentation or `nexus_extract`.

`hermes nexus route --shadow` may apply local rules, an opt-in classifier.dev
adapter, or an opt-in Hermes structured fallback. It never executes commands,
never writes review/Vault/index state, and never sends secret or sensitive text
to an external classifier. Configured confidence thresholds affect only
`needs_human_review` / `review_band`. They do not authorize execution
(`would_execute` stays false).

A `pre_llm_call` hook may inject that same shadow metadata into the current
Hermes user turn. The hook fails open on error, does not call tools, and does
not treat a label as permission to act.

## Extension footprint

NEXUS follows Hermes's footprint ladder:

1. plugin CLI command;
2. plugin-owned auxiliary LLM task;
3. optional skill after search/review commands exist;
4. fixed cron scripts after local canary;
5. no new core tool in v0.1.

## Current ingestion invariant

Dry-run and shadow ingestion remain read-only. Private staging is a separate,
explicit exact-path and SHA-confirmed mode: all bounded model calls finish before
any write, then only the content-addressed raw/quarantine store, source-lineage
state and append-only review queue may change. Staging never writes the Vault or
publishes a candidate. Canonical publication remains a separate reviewed and
exact-ID-confirmed operation.
