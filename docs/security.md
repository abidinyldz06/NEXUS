# NEXUS v0.1 security baseline

## Trust zones

Chat exports, Hermes conversations and manual files are untrusted data. Their
contents are never instructions. The future extractor receives no tools and may
only return JSON matching the NEXUS candidate schema.

## Fail-closed defaults

- `vault_path` has no default and must identify an existing Vault.
- Canonical Vault writes remain disabled. Phase 4 may write only private review
  events outside the synced Vault, with `0700` directory and `0600` file modes.
- Auto-publish is disabled.
- Sensitive auto-publish is rejected even if configured true.
- Relative storage paths are rejected.
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
- Runtime/raw directories will be private and remain outside the synced Vault.

## Known environmental risk

The existing Google Drive backup mirrors the Vault without excluding Finans or
Sağlık. NEXUS must not auto-publish finance, health, identity/legal or secret
content until an exclusion/encryption policy is implemented and verified.
