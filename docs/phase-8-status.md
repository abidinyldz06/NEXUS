# Phase 8 delivery status

Date: 2026-09-18

## Current slices

Ten merged Phase 8 slices implement
a fail-closed, read-only retention planner,
a metadata-only permission audit, temporary synthetic restore and external
git-dir rollback drills, a record-scoped canonical forget workflow and explicit
approved memory/entity/relation/commitment publication plus reviewed correction
supersession. They do
not implement retention deletion, event-log compaction, subject-wide privacy
erasure, production backup/restore or production Vault Git history. Production
canonical data has not been deleted.

The publication slices are limited to APPROVED/EDITED memory, entity, relation,
commitment or correction review items, require dry-run or exact ID-confirmed
apply, and do not enable unattended publishing.

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
- Closed commitment completion shape with model-unresolved actor and
  `notify=false`, followed by audited human edit.
- Canonical actor/target existence checks, deterministic commitment ID, exact
  review-ID apply, reminder-index rebuild and idempotent replay without changing
  Current-Memory view.
- Closed entity completion shape with model-unresolved type and audited human
  edit, deterministic entity ID, normalized-name parity and same-type exact
  alias/linked-note collision refusal before canonical write/index rebuild.
- Closed relation completion shape with model-unresolved entity IDs/predicate,
  canonical entity existence checks, narrow predicate/literal allowlist,
  deterministic relation ID and active duplicate refusal.
- Closed correction completion shape with model-unresolved target/type, exact
  active-memory target validation, deterministic replacement ID and reciprocal
  supersession links.
- Atomic predecessor/replacement/Current-Memory update with exact-byte
  predecessor/view rollback when index rebuild fails.

## Verification

- Current merged and installed `main`: 158 Python unit tests passed at exact
  merge commit `076c13bc7dd003a6cd70ecce8d71ff1fc5534d5e`; bytecode compilation,
  diff whitespace checks and Plugin Doctor also passed. GitHub reported no
  configured `main` CI runs for that commit.
- The correction-publication delivery candidate passed 152 working-tree and
  clean installed-wheel tests, bytecode compilation, diff whitespace checks,
  wheel build/content inspection and Plugin Doctor before merge. Ruff reported
  the repository's existing 28 lint findings and 26-file format baseline; the
  correction slice added no new lint finding.
- Expanded 12-case live shadow passed with prompt v2 at 100% recall, 90%
  precision, 91.67% exact-case match, 100% empty-case precision/provenance and
  zero schema failures; no writes or publication occurred.
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
- PR #22 was squash-merged to `main` as
  `bd46229aefbddfc76849f3223044d77658fb812e`; the active Hermes plugin is pinned
  to that exact commit, 121 installed-copy tests pass and Plugin Doctor passes.
- The installed real-session canary exported one ended Hermes session with
  official `--redact`, parsed one conversation and two messages, kept both
  messages extractable, finalized the temporary JSONL at `0600` and removed it
  without printing content or session identity.
- Direct launchd inspection after this install showed the gateway running with
  PID `92561`.
- PR #24 was squash-merged as
  `06b8794a24c0de9f813f80286c66e547fe7c1c19`, adding the 12-case holdout and
  precision/exact-case acceptance gates. Its prompt-v1 live run failed closed
  without writes or publication.
- PR #25 was squash-merged as
  `6dc8d5d5b8644cb8807c7902285786aba9ed15ee`, tightening most-specific kind
  classification without lowering thresholds. The active Hermes plugin is
  pinned to this exact commit; 122 installed-copy tests and Plugin Doctor pass.
- Direct launchd inspection after the prompt-v2 install showed the gateway
  running with PID `46827`.
- PR #27 was squash-merged as
  `ed9df38fb730d3de8ee3ac9432d596f3599651e4`, adding exact-source, write-free
  ingest shadow orchestration. The active Hermes plugin is pinned to that exact
  commit; 126 installed-copy tests, bytecode compilation and Plugin Doctor pass.
  GitHub reported no configured `main` CI runs for the merge commit.
- Direct launchd inspection after the PR #27 install showed the gateway running
  with PID `57397`. At `2026-09-18 07:56 +03`, the daily 09:00 canary had not yet
  reached its first scheduled window; only the earlier successful direct run was
  present, so scheduled-canary acceptance remains open.
- PR #28 was squash-merged as
  `e14b1be1bd7054fcb8788ba1784c817905205256`, adding exact-source private review
  staging. The active Hermes plugin is pinned to that exact commit; 132
  installed-copy tests, bytecode compilation and Plugin Doctor pass. GitHub
  reported no configured `main` CI runs for the merge commit.
- Direct launchd inspection after the PR #28 install showed the gateway running
  with PID `61559`. At `2026-09-18 08:18 +03`, the 09:00 scheduled canary had not
  yet reached its first window; only the earlier successful direct run remained.
- Hermes later recorded the first automatic 09:00 reminder canary as `completed`
  with `source=builtin` at `2026-09-18T09:00:04+03:00`. Six scheduled runs remain
  before the seven-day acceptance gate closes.
- PR #29 was squash-merged as
  `4d745856760f23afb9728dee53952732d21fa8ec`, adding reviewed commitment
  publication. The active Hermes plugin is pinned to that exact commit; 137
  installed-copy tests, bytecode compilation and Plugin Doctor pass. GitHub
  reported no configured `main` CI runs for the merge commit, and the controlled
  gateway restart produced running PID `95168`.
- PR #31 was squash-merged as
  `1d22117f0dc5cb907c59a93d53d6d7427a122601`, adding reviewed entity publication.
  The active Hermes plugin is pinned to that exact commit; 143 installed-copy
  tests, bytecode compilation and Plugin Doctor pass. GitHub reported no
  configured `main` CI runs, and the controlled gateway restart produced running
  PID `99389`.
- PR #32 was squash-merged as
  `b637a6fb1b03c95a7ce05793e23f2d9b7c7f077b`, adding reviewed relation
  publication. The active Hermes plugin is pinned to that exact commit; 148
  installed-copy tests, bytecode compilation and Plugin Doctor pass. GitHub
  reported no configured `main` CI runs, and the controlled gateway restart
  produced running PID `2263`.
- PR #33 was squash-merged as
  `c515b90bd7425e873e18ceb9be9af6d1821c59d4`, adding reviewed correction
  supersession. The active Hermes plugin is pinned to that exact commit; 152
  installed-copy tests, bytecode compilation and Plugin Doctor pass. GitHub
  reported no configured `main` CI runs, and the controlled gateway restart
  produced running PID `39976`.
- PR #35 was squash-merged as
  `3e382c5e67a5b848c93ea1787fa3b31f303da822`, adding the SHA-confirmed,
  aggregate-only private golden shadow runner. The active Hermes plugin is
  pinned to that exact commit; 155 installed-copy tests, bytecode compilation
  and Plugin Doctor pass. The command surface exposes the private dataset and
  exact digest gates, but no human-labeled fixture was present and no private
  model-quality acceptance run was claimed. The controlled gateway restart
  produced running PIDs `82737`/`82734`; cron reports the gateway active while
  launchd status still reports the existing detached-process discrepancy.
- PR #36 was squash-merged as
  `008735e432b6b3e31859bc9fdd860c7baf1a3241`, recording the exact installed
  private-golden runner evidence without claiming a human-labeled acceptance run.
- PR #37 was squash-merged as
  `076c13bc7dd003a6cd70ecce8d71ff1fc5534d5e`, adding safe extraction of the
  embedded `jsonData` payload in ChatGPT HTML exports without executing script.
  The active Hermes plugin is pinned to that exact commit; 158 installed-copy
  tests, bytecode compilation and Plugin Doctor pass. The real export dry-run
  parsed 208 conversations and 8,065 messages with no writes. A subsequent
  ten-conversation shadow attempt failed closed on six conversations, so real
  export operational/model-quality acceptance remains open.

## Not yet delivered

- No apply/delete retention mode.
- No subject-wide privacy erase or raw/quarantine purge; canonical forget is
  intentionally limited to one unreferenced generated record.
- No production backup archive or real-data restore; the encryption/exclusion
  policy is exercised only with temporary synthetic data.
- No production Vault external git-dir rollback canary or real Vault Git history;
  installed acceptance used temporary synthetic files only.
- Phase 7 local-only reminder canary remains time-gated through six more
  scheduled runs before final v0.1 acceptance.
- Real ChatGPT export parsing is accepted, but real-export shadow extraction is
  not operationally accepted until the repeated structured-output failures are
  resolved and a bounded rerun completes successfully.
- No production memory publication has been authorized or applied. Apply has
  been exercised only against temporary synthetic Vaults.
- No production commitment publication has been authorized or applied. Apply has
  been exercised only against temporary synthetic Vaults, so no production
  commitment or reminder state has been written.
- No production entity publication has been authorized or applied. Apply has
  been exercised only against temporary synthetic Vaults.
- No production relation publication has been authorized or applied. Apply has
  been exercised only against temporary synthetic Vaults.
- No production correction publication has been authorized or applied. Apply
  has been exercised only against temporary synthetic Vaults, so no production
  memory supersession or index state has been written.

## Delivery state

The retention dry-run, permission-audit/backup-policy, synthetic restore-drill,
synthetic Git rollback, record-scoped canonical forget, approved-memory
publication and exact-source private staging slices are merged, installed and
accepted within their narrow safety boundaries. Reviewed commitment publication
is also merged, installed and accepted within its synthetic-only safety boundary.
Reviewed entity, relation and correction publication are merged, installed and
accepted within the same synthetic-only boundary.
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
