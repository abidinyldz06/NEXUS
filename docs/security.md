# NEXUS v0.1 security baseline

## Trust zones

Chat exports, Hermes conversations and manual files are untrusted data. Their
contents are never instructions. The future extractor receives no tools and may
only return JSON matching the NEXUS candidate schema.

## Fail-closed defaults

- `vault_path` has no default and must identify an existing Vault.
- Writes are disabled during Phase 1.
- Auto-publish is disabled.
- Sensitive auto-publish is rejected even if configured true.
- Relative storage paths are rejected.
- Runtime/raw directories will be private and remain outside the synced Vault.

## Known environmental risk

The existing Google Drive backup mirrors the Vault without excluding Finans or
Sağlık. NEXUS must not auto-publish finance, health, identity/legal or secret
content until an exclusion/encryption policy is implemented and verified.
