# Phase 2 delivery status

Date: 2026-09-18

## Outcome

Phase 2 is locally implemented with one explicit acceptance hold: the ChatGPT
adapter is validated against a synthetic `conversations.json` fixture, not a real
user export. It must not be described as real-export compatible until that private
shape is inspected without committing its contents.

Dry-run and shadow ingestion remain write-free. A separate exact-source staging
mode now connects extraction to owner-private raw/source state and the review
queue, while keeping the canonical Vault and publication path untouched.

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
- Exact path + SHA-gated `hermes nexus ingest --shadow`; multi-conversation
  sources require an exact conversation ID and model calls are bounded to 1–100
  segments before execution.
- Shadow output contains only source shape, candidate-kind counts and model audit
  totals; candidate statements and source content are never printed or persisted.
- Exact path + SHA-gated `hermes nexus ingest --stage` completes every bounded
  model call before writing, archives or quarantines the source by content hash,
  updates source lineage idempotently and enqueues reviewable candidates without
  canonical publication.
- Stage output is aggregate-only. Policy discard/quarantine candidates are not
  written to review, repeated runs reuse the existing review fingerprint and
  extracted memory candidates require a human-selected subtype before publish.
- Extracted commitment candidates use a closed completion shape with unresolved
  actor and `notify=false`; actor/target/date/notification choices remain an
  audited human edit rather than model authority.
- Extracted entity candidates use a closed completion shape with unresolved
  entity type. A single mention may prefill the display/normalized name, but the
  canonical type remains an audited human choice.
- Extracted relation candidates use a closed completion shape with unresolved
  source/target entities and predicate. The model cannot select canonical IDs or
  an allowed predicate for publication.

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
- Current merged and installed suite: 143 tests passed. Shadow coverage proves exact SHA,
  aggregate-only output, no private writes, explicit multi-conversation selection
  and pre-model segment-limit refusal.
- Current relation-publication branch: 148 tests passed; staging keeps relation
  entity IDs and predicate unresolved until an audited human edit.
- Synthetic stage coverage proves wrong-SHA and model-failure zero-write behavior,
  owner-only raw/state modes, review idempotency, quarantine routing and zero
  Vault writes. No configured production Inbox source was staged.

## Remaining gate

- Inspect one suitable real ChatGPT `conversations.json` export in place.
- Record any format delta and add only a redacted/minimized regression fixture.
- Re-run the Phase 2 suite and exact-source Hermes ingest shadow before marking
  Phase 2 fully accepted.
- Run staging against a specifically approved real target only after the export
  shape passes shadow validation; private raw/review writes are not implied by
  read-only acceptance.

The Hermes official-export shape is accepted. The user explicitly chose to
proceed on 2026-09-16 with ChatGPT support marked experimental. That separate
source-format gate remains open and is not silently waived.
