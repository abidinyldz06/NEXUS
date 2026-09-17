# Phase 8 delivery status

Date: 2026-09-17

## Current slice

The first Phase 8 slice implements a fail-closed, read-only retention planner.
It does not implement deletion, event-log compaction, forget, backup, restore or
Git rollback operations.

## Implemented

- `hermes nexus retention --dry-run` explicit safety gate.
- Raw expiry planning from `raw_retention_days` (default 90 days).
- Quarantine and rejected-candidate planning from
  `rejected_retention_days` (default 30 days).
- Aggregate-only output with no source paths, candidate IDs or candidate text.
- Non-symlink absolute `data_path` validation and no-follow tree traversal.
- Missing private-data directories remain missing; dry-run creates no state.
- Rejected review expiry uses the timezone-aware decision audit timestamp.

## Verification

- Python 3.11 unit tests: 97 passed.
- Old/fresh raw and quarantine boundaries passed.
- Rejected candidate expiry passed while preserving the append-only event log.
- Symlinked data path failed closed; nested symlink entries were not followed.
- CLI refused retention without `--dry-run`.
- Bytecode compilation and diff whitespace checks passed.

## Not yet delivered

- No apply/delete retention mode.
- No forget workflow.
- No sensitive-backup encryption/exclusion decision or restore drill.
- No external git-dir rollback canary.
- No production installation or production retention scan.
- Phase 7 local-only reminder canary remains time-gated through seven scheduled
  runs before final v0.1 acceptance.

## Delivery state

The implementation is local on `codex/nexus-phase8-retention-dry-run`. It has
not been committed, pushed, merged or installed in the active Hermes plugin.
