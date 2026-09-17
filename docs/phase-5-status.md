# Phase 5 delivery status

Date: 2026-09-17

## Outcome

Phase 5 is implemented and locally validated on
`codex/nexus-phase5-vault-writer`. Canonical records can be rendered and written
atomically below a temporary Vault's managed `Nexus/` namespace with exact
provenance, optimistic content preconditions, rollback and run audit.

No write was made to the configured production Obsidian Vault. The active
Hermes plugin remains pinned to the merged Phase 4 commit, auto-publish remains
disabled, and the gateway, cron jobs, backup and user configuration were not
modified during Phase 5 implementation.

## Implemented

- Fixed immutable-ID paths for source, memory, entity, relation, commitment and
  review records.
- Deterministic human-readable Markdown plus embedded rebuildable JSON payload.
- HTML and Obsidian Markdown control-character neutralization for untrusted text.
- Derived canonical records require at least one exact `SourceRef`.
- Writes are contained below `Nexus/`; absolute paths, traversal and symlink
  components fail closed.
- Create-only default and SHA-256 preconditions for every update.
- Staged multi-file writes, fsync/replace, rollback and per-run audit manifests.
- Incomplete rollback preserves recovery staging rather than deleting backups.
- Memory correction creates a new ID, links `supersedes/superseded_by` and keeps
  the historical record accessible.
- Generated current-memory view contains active records only.

## Verification

- Hermes Python 3.11 unit tests: 72 passed.
- Twenty generated canonical memories round-tripped to exact source span IDs and
  span hashes.
- Temporary Vault E2E covered create, preconditioned update, stale conflict,
  path escape, symlink escape, injected failure rollback and correction views.
- Existing record bytes were restored and newly created files removed after an
  injected transaction failure.
- A simulated concurrent edit was not overwritten during rollback; the
  transaction failed closed and preserved its recovery staging.
- Content preconditions are rechecked immediately before `os.replace`; a
  simulated edit in that window remained untouched.
- Superseded memory remained readable while the generated view showed only its
  active replacement.
- Python bytecode compilation passed.
- Scoped Ruff 0.16.8 passed for all Phase 5 Python files.
- `hermes plugins doctor . --ci` passed discovery, import and registration with
  zero tools and zero hooks.
- Wheel build passed and includes `nexus/corrections.py` and all `nexus/vault`
  modules.

## Remaining acceptance gates

- Review and commit this local diff; it is not pushed, merged or installed.
- Run a narrowly scoped production Vault canary only after separate explicit
  approval and a pre-write inventory/hash snapshot.
- Keep auto-publish disabled until the 7-day shadow gate and backup policy are
  accepted.
- Real ChatGPT export acceptance remains open; its adapter is experimental.
