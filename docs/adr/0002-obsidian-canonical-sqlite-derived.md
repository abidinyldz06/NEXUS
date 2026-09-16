# ADR 0002: Obsidian is canonical; SQLite is derived

Status: accepted for v0.1

Memory, source, entity, relation, commitment and review records will be stored as
human-readable Markdown under the existing Vault's future `Nexus/` namespace.
SQLite will provide FTS5, fingerprints, scheduling state and fast lookups.

Deleting SQLite must not lose canonical information. `nexus rebuild` will recreate
it from Markdown records without a model call or raw export.
