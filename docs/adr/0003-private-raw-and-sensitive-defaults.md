# ADR 0003: Keep raw data private and sensitive publication disabled

Status: accepted default; backup remediation still pending

Raw conversation exports will live under `~/.local/share/nexus`, not inside the
iCloud/Syncthing/Google Drive-backed Vault. The human-facing Inbox may be
`~/Nexus/Inbox`, but successful ingestion archives into the private data path.

Finance, health, identity/legal and secret-like content cannot auto-publish while
the existing off-device backup policy remains plaintext for those categories.
