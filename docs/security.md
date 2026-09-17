# NEXUS v0.1 security baseline

## Trust zones

Chat exports, Hermes conversations and manual files are untrusted data. Their
contents are never instructions. The future extractor receives no tools and may
only return JSON matching the NEXUS candidate schema.

## Fail-closed defaults

- `vault_path` has no default and must identify an existing Vault.
- Canonical auto-publish remains disabled. Phase 4 may write private review
  events outside the synced Vault; an approved/edited memory may be published
  only through the explicit dry-run/apply command and exact review-ID
  confirmation. Phase 7 may update only `notified_at` on an existing approved
  commitment through the explicit local reminder command.
- Auto-publish is disabled.
- Sensitive auto-publish is rejected even if configured true.
- Relative storage paths are rejected.
- Official Hermes exports must target an existing owner-only, non-symlink
  directory. Successful JSONL output is opened without following symlinks and
  tightened to `0600` before the wrapper returns it.
- Review edit input must be an absolute, regular, non-symlink JSON file no larger
  than 1 MiB and must preserve the candidate's existing fields.
- Phase 5 canonical writer accepts only generated relative paths below `Nexus/`,
  rejects symlink traversal and requires content-hash preconditions for updates.
- Untrusted human text is escaped inside `<pre>`; the rebuild payload is
  deterministic JSON encoded as URL-safe base64 rather than executable Markdown.
- A transaction failure restores existing records and removes newly created
  records. If rollback cannot finish, recovery staging is preserved for manual
  inspection instead of being silently deleted.
- Phase 6 rebuild reads only generated canonical record directories, rejects
  symlink traversal and malformed or path-mismatched payloads, then atomically
  replaces a `0600` SQLite database outside the Vault.
- Search opens SQLite read-only, treats query text as literal terms, binds all
  query/filter values as SQL parameters and limits results to at most 100.
- Phase 7 reminder output accepts only approved/edited/auto-reviewed open
  commitments with explicit non-ambiguous dates and `notify=true`.
- Reminder state uses canonical `notified_at`, immutable-ID paths and SHA-256
  content preconditions. A post-write index failure restores exact prior bytes.
- Cron wrappers use argument-vector subprocess calls with no shell and no agent;
  empty reminder output is silent. No external delivery target is configured.
- Retention starts as aggregate-only dry-run: raw/quarantine paths are scanned
  without following symlinks, rejected candidate IDs/content are not printed,
  and no delete, rewrite or apply mode exists.
- Canonical forget starts with a read-only impact plan. Apply requires the exact
  target ID a second time, refuses any canonical dependency, rechecks the target
  content hash immediately before deletion, rebuilds the disposable index and
  writes a content-free private audit event. View/index/audit failure restores
  exact prior bytes; concurrent changes prevent unsafe rollback.
- Approved-memory publication accepts only a closed memory-candidate shape,
  preserves exact source references, rejects missing canonical entity links and
  derives one stable memory ID from the review ID. Apply requires the review ID
  again and writes the record plus Current-Memory view in one Vault transaction.
- A publication index failure restores the new record and generated view while
  preserving the prior disposable index. A later private review-audit failure
  is reported as incomplete rather than claiming rollback: retry verifies the
  deterministic canonical content, rebuilds the index and appends the missing
  audit without rewriting the Vault record.
- Permission audit reads metadata only, reports aggregate issue counts and
  treats symlinks, non-regular entries, ownership mismatch and group/world
  access as failures without changing modes.
- Derived SQLite is excluded from authoritative backup. Private raw/review data
  is excluded by default and requires encrypted, owner-only staging plus an
  explicitly approved destination before backup.
- Synthetic Git rollback uses argument-vector commands without a shell, disables
  system/global config and templates/hooks, keeps metadata outside its temporary
  worktree and never reads the configured production Vault.
- Runtime/raw directories will be private and remain outside the synced Vault.

The canonical forget command is record-scoped, not a subject-wide privacy erase.
It does not remove raw/quarantine exports or arbitrary copies outside generated
canonical records; those remain separate destructive workflows.

## Known environmental risk

The existing Google Drive backup mirrors the Vault without excluding Finans or
Sağlık. NEXUS must not auto-publish finance, health, identity/legal or secret
content until an exclusion/encryption policy is implemented and verified.
