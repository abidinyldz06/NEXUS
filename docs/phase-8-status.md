# Phase 8 delivery status

Date: 2026-09-17

## Current slices

The first two Phase 8 slices implement a fail-closed, read-only retention planner
and a metadata-only permission audit. They do not implement deletion, event-log
compaction, forget, backup, restore or Git rollback operations.

## Implemented

- `hermes nexus retention --dry-run` explicit safety gate.
- Raw expiry planning from `raw_retention_days` (default 90 days).
- Quarantine and rejected-candidate planning from
  `rejected_retention_days` (default 30 days).
- Aggregate-only output with no source paths, candidate IDs or candidate text.
- Non-symlink absolute `data_path` validation and no-follow tree traversal.
- Missing private-data directories remain missing; dry-run creates no state.
- Rejected review expiry uses the timezone-aware decision audit timestamp.
- Read-only permission audit for private data and Inbox ownership/access bits.
- Aggregate permission findings without entry paths, names or file content.
- Backup classification and encrypted/excluded sensitive-data policy in
  `docs/backup-policy.md`.

## Verification

- Python 3.11 unit tests: 101 passed.
- Old/fresh raw and quarantine boundaries passed.
- Rejected candidate expiry passed while preserving the append-only event log.
- Symlinked data path failed closed; nested symlink entries were not followed.
- CLI refused retention without `--dry-run`.
- Bytecode compilation and diff whitespace checks passed.
- PR #9 was squash-merged to `main` as
  `0d6216ffc64e995a268afc9c20faa8111fadbb1b` and the active Hermes plugin is
  pinned to that exact commit.
- Plugin Doctor passed on the installed copy and the gateway restarted under
  launchd with a fresh PID.
- Production dry-run returned zero raw, quarantine and rejected candidates,
  reported `writes_performed=false`, and left both the SQLite hash and private
  file count unchanged.
- Permission audit tests cover private trees, group-readable files, nested
  symlinks and output redaction.
- PR #11 was squash-merged to `main` as
  `7cac1228facff63e08aae85053763720ba5c61be`; the active Hermes plugin is pinned
  to that exact commit and Plugin Doctor passes on the installed copy.
- The gateway restarted under launchd and direct `launchctl` inspection showed
  the supervised service running with a fresh PID.
- Production `audit permissions --json` checked two private-data entries with
  zero insecure or unsafe findings, reported `writes_performed=false`, and left
  the SQLite mode, size and SHA-256 unchanged. The configured Inbox was absent.

## Not yet delivered

- No apply/delete retention mode.
- No forget workflow.
- No backup archive or restore drill; the encryption/exclusion policy is
  documented but not operationally exercised.
- No external git-dir rollback canary.
- Phase 7 local-only reminder canary remains time-gated through seven scheduled
  runs before final v0.1 acceptance.

## Delivery state

The retention dry-run and permission-audit/backup-policy slices are merged and
installed. Their production acceptance is limited to read-only scans: retention
found no expiry candidates and permission audit found no insecure or unsafe
entries. No retention deletion, permission repair or backup capability exists.
