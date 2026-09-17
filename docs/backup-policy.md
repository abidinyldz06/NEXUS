# NEXUS backup and restore policy

Date: 2026-09-17

## Classification

- Canonical Obsidian records are the durable source of truth.
- `~/.local/share/nexus/nexus.db` is derived and must be rebuilt, not restored
  as authoritative data.
- Raw exports, quarantine and review events are private sensitive data outside
  the Vault.
- The plugin checkout and cron wrapper are reproducible from an exact merged
  Git commit.

## Backup decision

- Derived SQLite files and sidecars are excluded from durable backup.
- Raw, quarantine and review data are excluded by default. Any future backup of
  them must be encrypted at rest, owner-only while staged, and explicitly
  approved for its destination and retention window.
- A Hermes backup must be treated as sensitive because it can contain config,
  credentials, cron state and conversation/session data. NEXUS does not assume
  that data outside `HERMES_HOME` is included; archive manifests must be checked
  without printing secret values.
- Canonical Vault backup follows the Vault provider's existing protected backup
  mechanism. NEXUS will not copy the whole Vault or create an unencrypted mirror.
- Git may protect canonical Markdown history only when metadata is stored
  outside the Vault and a small non-sensitive canary proves rollback. Raw,
  quarantine, review logs, SQLite and secrets must never be committed.

## Restore boundary

- Restore drills use temporary directories and synthetic/canary records first.
- Production Vault, private data and Hermes state are never overwritten by a
  drill.
- Acceptance requires record/hash parity, derived-index rebuild parity and an
  explicit rollback point before any real restore is considered.

## Current state

No production archive, repository, external git directory or real restore is
created. The source branch includes a synthetic restore drill that uses only a
private temporary directory, verifies canonical hash and derived-index parity,
then removes the entire drill directory. Production backup and restore remain
separate, explicitly approved acceptance gates.
