# Phase 2 delivery status

Date: 2026-09-16

## Outcome

Phase 2 is locally implemented with one explicit acceptance hold: the ChatGPT
adapter is validated against a synthetic `conversations.json` fixture, not a real
user export. It must not be described as real-export compatible until that private
shape is inspected without committing its contents.

The active Hermes installation, Obsidian Vault, gateway, cron jobs, backup and
user configuration were not modified. The exposed CLI remains dry-run only.

## Implemented

- Provider-neutral normalized conversation/message contracts.
- Synthetic ChatGPT current-branch adapter.
- Hermes official full-session JSONL adapter and redacted export wrapper.
- Manual Markdown/text and non-rendering HTML adapter.
- Inbox extension, size, stability, containment and symlink checks.
- Descriptor-level no-follow reads and changed-during-read detection.
- Content-addressed private raw/quarantine store with no-overwrite publication.
- Atomic source lineage state with duplicate and growing-revision handling.
- Stable raw/source/message/segment/memory fingerprint helpers.
- `hermes nexus ingest --dry-run`; no archive, state or Vault writes.

## Verification

- Hermes Python 3.11: 35 unit tests passed.
- Python bytecode compilation passed.
- JSON Schema Draft 2020-12 meta-validation passed.
- `hermes plugins doctor . --ci` passed real discovery, import and registration.
- Isolated Hermes runtime discovered the enabled plugin and parsed one synthetic
  Hermes JSONL file as 1 conversation / 4 messages with `writes_performed: false`.
- One real ended Hermes session was exported through the official CLI with
  `--redact` into an owner-only temporary directory. The adapter parsed one
  conversation and two messages, both eligible for extraction, without printing
  content; the temporary export was removed immediately after validation.
- The real CLI initially created the JSONL as `0644`. The wrapper now rejects
  non-owner-only parent directories, starts the export under `umask 077` and
  tightens the output through a no-follow descriptor to `0600`; the same
  real-session canary then passed at `0600`.
- Repeating one source three times kept one source ID and revision 1.
- A changed conversation kept its source ID and advanced to revision 2.
- Symlink, oversize, format mismatch, malformed export and post-discovery mutation
  cases failed closed.

## Remaining gate

- Inspect one suitable real ChatGPT `conversations.json` export in place.
- Record any format delta and add only a redacted/minimized regression fixture.
- Re-run the Phase 2 suite and isolated Hermes dry-run before marking Phase 2
  fully accepted.

The Hermes official-export shape is accepted. The user explicitly chose to
proceed on 2026-09-16 with ChatGPT support marked experimental. That separate
source-format gate remains open and is not silently waived.
