# Phase 8 delivery status

Date: 2026-09-17

## Current slices

Six merged Phase 8 slices implement a fail-closed, read-only retention planner,
a metadata-only permission audit, temporary synthetic restore and external
git-dir rollback drills, a record-scoped canonical forget workflow and explicit
approved-memory publication. They do
not implement retention deletion, event-log compaction, subject-wide privacy
erasure, production backup/restore or production Vault Git history. Production
canonical data has not been deleted.

The sixth slice is limited to APPROVED/EDITED memory review items, requires
dry-run or exact ID-confirmed apply, and does not enable unattended publishing.

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
- Read-only `forget RECORD_ID --dry-run` impact planning with aggregate dependency
  counts and no record content in output.
- Exact-ID `--apply --confirm RECORD_ID` gate, dependency refusal, immediate
  content-hash precondition, generated memory-view update, derived-index rebuild
  and content-free private audit.
- Exact-byte target/view/index rollback when rebuild or audit fails, with
  fail-closed handling for concurrent changes.
- Read-only approved-memory publication planning with a deterministic target ID.
- Exact-review-ID apply gate, closed candidate shape, preserved provenance and
  validation of canonical entity references.
- Atomic canonical memory and Current-Memory view write followed by derived-index
  rebuild and a private publication event.
- Idempotent repeat apply and recovery of a missing private review audit without
  rewriting canonical Vault bytes.
- Exact target/view rollback when initial publication index rebuild fails.

## Verification

- Python 3.11 unit tests: 120 passed on `main` and the installed plugin copy.
- Hermes export permission hardening source branch: 121 tests passed; installed
  acceptance remains pending until merge.
- Approved-memory publication coverage includes CLI dry-run/apply, provenance,
  idempotency, rollback, audit retry and legacy v1 schema compatibility.
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
- PR #15 was squash-merged to `main` as
  `74ebf71ea5f065c6b133543b5440cf88d847af83`; the active Hermes plugin is pinned
  to that exact commit and Plugin Doctor passes on the installed copy.
- The gateway restarted under launchd with PID `23427`. Production execution of
  `drill git-rollback --synthetic --json` verified six files, external metadata,
  no worktree `.git` entry, controlled mutation detection, exact-commit rollback,
  hash parity, a clean worktree, private permissions and cleanup.
- The Git drill reported no production path access or writes. Production SQLite
  mode `0600`, size `57344`, SHA-256
  `a1a098d0006b1bf51896d575884a354d8201559455fae5d2ddedd5de5456c0fa` and the
  private file count remained unchanged, and no temporary drill directory remained.
- Forget workflow tests cover dependency refusal, exact confirmation, successful
  synthetic deletion, memory-view/index parity, private audit permissions and
  exact rollback after rebuild or audit failure. Concurrent target changes are
  preserved and force an incomplete-rollback error instead of being overwritten.
- PR #17 was squash-merged to `main` as
  `ad73a45c08ee3016e1d5cc899587f59b7d5c4c92`; the active Hermes plugin is pinned
  to that exact commit and Plugin Doctor passes on the installed copy.
- The gateway restarted under launchd with PID `26988`. Production execution of
  forget dry-run with a valid nonexistent target returned `record not found`,
  `writes_performed=false` and exit code `2`, proving the command surface and
  fail-closed path without selecting or deleting a real record.
- Production SQLite mode `0600`, size `57344`, SHA-256
  `a1a098d0006b1bf51896d575884a354d8201559455fae5d2ddedd5de5456c0fa` and the
  private file count of one remained unchanged after the dry-run.
- PR #19 was squash-merged to `main` as
  `3c70434749b066d00daff92e01416cf1ba63b1ee`; that feature commit passed 120
  installed-copy tests and Plugin Doctor.
- A production-safe publish dry-run used a valid but nonexistent review ID. It
  returned `review item was not found`, exit code `2`,
  `writes_performed=false` and `vault_writes=false` without selecting a real
  review item or canonical record.
- The production SQLite mode/size and SHA-256 were unchanged, and the private
  file count remained one before and after the publish dry-run.
- Direct launchd inspection showed `ai.hermes.gateway` running with PID `82652`.
  `hermes gateway status` saw PIDs `82652`/`82653` but simultaneously reported
  the service as not loaded; this status-reporting discrepancy remains open.
- PR #20 was squash-merged to `main` as
  `79aa60329f32f201fb67612132d41205e6a03c0b`. It records acceptance evidence and
  corrects `status.write_scope` to `explicit-confirmed-operations` without
  widening any write gate.
- The active Hermes plugin is pinned to that exact PR #20 commit; 120
  installed-copy tests and Plugin Doctor pass. Runtime status reports
  `auto_publish_enabled=false`, the corrected write scope and no config errors.
- Direct launchd inspection after the final restart showed the gateway running
  with PID `85639`.

## Not yet delivered

- No apply/delete retention mode.
- No subject-wide privacy erase or raw/quarantine purge; canonical forget is
  intentionally limited to one unreferenced generated record.
- No production backup archive or real-data restore; the encryption/exclusion
  policy is exercised only with temporary synthetic data.
- No production Vault external git-dir rollback canary or real Vault Git history;
  installed acceptance used temporary synthetic files only.
- Phase 7 local-only reminder canary remains time-gated through seven scheduled
  runs before final v0.1 acceptance.
- No production memory publication has been authorized or applied. Apply has
  been exercised only against temporary synthetic Vaults.

## Delivery state

The retention dry-run, permission-audit/backup-policy, synthetic restore-drill,
synthetic Git rollback, record-scoped canonical forget and approved-memory
publication slices are merged, installed and accepted within their narrow
safety boundaries.
Retention found no expiry candidates, permission audit found no insecure or
unsafe entries, and both drill verifications used temporary synthetic data only.
No retention deletion, permission repair, production backup capability or
production Vault Git history exists.

Forget apply was exercised only with temporary synthetic records. Production
acceptance used a missing-target dry-run; no production canonical record, raw
file, review event or Vault path was changed.

Memory publish apply was exercised only with temporary synthetic records.
Production acceptance used a missing-review dry-run; no production review event,
canonical record, generated view or derived index was changed.
