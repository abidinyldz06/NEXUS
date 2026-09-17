# Phase 6 delivery status

Date: 2026-09-17

## Outcome

Phase 6 is implemented and locally validated on
`codex/nexus-phase6-sqlite-index`. Canonical Markdown remains authoritative;
SQLite is a disposable derived index that can be deleted and rebuilt without a
model call or raw export.

No write was made to the configured production Obsidian Vault. The active
Hermes plugin remains pinned to the merged Phase 5 commit, canonical writes and
auto-publish remain disabled, and cron, notification, backup and user
configuration were not modified during Phase 6 implementation.

## Implemented

- Schema-versioned SQLite migration runner and packaged initial schema.
- FTS5 index using Unicode tokenization plus structured kind/status indexes.
- Structured commitment queue fields and due-date index.
- Canonical record scan limited to managed `Nexus/` record directories.
- Payload schema, immutable ID/filename and symlink safety validation.
- Full rebuild beside the live database followed by fsync and atomic replace.
- Read-only search with literal query terms, parameterized filters and bounded
  result count.
- `hermes nexus rebuild` and `hermes nexus search` CLI commands.

## Verification

- Python 3.11 unit tests: 77 passed.
- Delete/rebuild parity preserved canonical record IDs, content hashes and open
  commitment counts.
- Turkish FTS search, kind filtering and hostile query text passed.
- Migration idempotency and missing/corrupt index fail-closed paths passed.
- CLI rebuild/search integration reported `vault_writes: false`.
- Python bytecode compilation and diff whitespace checks passed.
- Scoped Ruff passed for all Phase 6 files.

## Remaining acceptance gates

- Review and commit this local diff; it is not pushed, merged or installed.
- Run plugin doctor and wheel-content verification for the final diff.
- Do not rebuild the production index until this branch is merged and the exact
  merged commit is installed.
- Canonical Vault canary, auto-publish and reminders remain separate gates.
- Real ChatGPT export acceptance remains open; its adapter is experimental.
