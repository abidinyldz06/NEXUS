# Canonical forget workflow

Date: 2026-09-17

## Safety boundary

This workflow removes exactly one generated canonical NEXUS record. It is not a
subject-wide privacy erasure and does not purge raw exports, quarantine files,
review event history or arbitrary copies outside the canonical record tree.

The target must be an immutable NEXUS record ID. Dry-run scans canonical records
without writing and reports only the target kind plus aggregate dependency
counts. It never prints record content or dependent record IDs.

## Required sequence

```bash
hermes nexus forget RECORD_ID --dry-run --json
hermes nexus forget RECORD_ID --apply --confirm RECORD_ID --json
```

Apply is refused when `--confirm` differs from the target or any other canonical
record contains an exact reference to it. The target hash is checked again
immediately before deletion.

For a memory record, the generated current-memory view is rebuilt without the
target. The disposable SQLite index is then rebuilt from the remaining canonical
records. A private `0600` audit event records only opaque IDs, hashes and counts;
it contains no canonical record text.

If view generation, index rebuild or audit persistence fails, the target, view
and index are restored to their exact prior bytes. A concurrent change that
cannot be proven safe causes rollback to fail closed rather than overwriting the
external change.

## Production gate

Installing the command does not authorize a production deletion. Each real
target still requires a target-specific dry-run followed by the exact-ID apply
command. The workflow is installed from merge commit
`ad73a45c08ee3016e1d5cc899587f59b7d5c4c92`; Phase 8 acceptance used synthetic
apply tests and a missing-target production dry-run, never a production target.
