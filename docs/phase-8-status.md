# Phase 8 delivery status

Date: 2026-09-17

## Current slices

Three merged Phase 8 slices implement a fail-closed, read-only retention planner,
a metadata-only permission audit and a temporary synthetic restore drill. They
do not implement deletion, event-log
compaction, forget, production backup/restore or Git rollback operations.
A fourth source-branch slice adds a temporary synthetic external git-dir rollback
drill without enabling production Vault history.

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
- Explicit `drill restore --synthetic` gate that never reads plugin config or
  production paths.
- Four deterministic synthetic canonical records, private temporary snapshot and
  restore trees, exact file-hash comparison and independent SQLite rebuild parity.
- Fail-closed restore corruption detection and verified temporary-directory cleanup.
- Explicit `drill git-rollback --synthetic` gate that ignores plugin config and
  production paths.
- Six private synthetic files committed through metadata outside the temporary
  worktree, mutation detection, exact-commit rollback, hash parity and clean-tree
  verification.
- Isolated Git execution with no shell, system/global config, templates or hooks.

## Verification

- Python 3.11 unit tests: 109 passed on the source branch.
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
- Synthetic restore tests cover successful hash/index/permission/cleanup parity,
  corruption failure, symlinked temporary-parent rejection and the CLI safety
  gate without reading user config.
- PR #13 was squash-merged to `main` as
  `6690fd83c4f0d63bb2df21e8761b781c2f2bc458`; the active Hermes plugin is pinned
  to that exact commit and Plugin Doctor passes on the installed copy.
- The gateway restarted under launchd with PID `19358`. Production execution of
  `drill restore --synthetic --json` verified four records, five canonical files,
  one open commitment, canonical hash parity, independent index parity, private
  permissions and cleanup.
- The drill reported no production path access or writes. The production SQLite
  mode, size, SHA-256 and private file count remained unchanged, and no temporary
  drill directory remained.
- Synthetic Git rollback tests cover six-file parity, external metadata, absence
  of a worktree `.git` entry, missing-Git failure, symlinked-parent rejection and
  the CLI safety gate without reading user config.

## Not yet delivered

- No apply/delete retention mode.
- No forget workflow.
- No production backup archive or real-data restore; the encryption/exclusion
  policy is exercised only with temporary synthetic data.
- No production Vault external git-dir rollback canary; the source-branch drill
  uses temporary synthetic files only.
- Phase 7 local-only reminder canary remains time-gated through seven scheduled
  runs before final v0.1 acceptance.

## Delivery state

The retention dry-run, permission-audit/backup-policy and synthetic restore-drill
slices are merged, installed and accepted within their narrow safety boundaries.
Retention found no expiry candidates, permission audit found no insecure or
unsafe entries, and restore verification used temporary synthetic data only. No
retention deletion, permission repair or production backup capability exists.

The synthetic Git rollback slice is local on
`codex/nexus-phase8-git-rollback-drill`; it has not been pushed, merged or
installed in the active Hermes plugin.
