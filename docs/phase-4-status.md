# Phase 4 delivery status

Date: 2026-09-16

## Outcome

Phase 4 is implemented and locally validated on
`codex/nexus-phase4-policy-review`. It converts candidate metadata into pure,
deterministic shadow decisions and provides a private, replayable review queue.
No canonical Vault record is written and an approval does not publish data.

The active Hermes installation, Vault, gateway, cron jobs, backup and user
configuration were not modified during this phase. Active Hermes still points
to the previously installed Phase 3 source commit until this branch is reviewed
and deliberately installed.

## Implemented

- Stable-ID, exact normalized typed-alias and exact linked-note resolution.
- No fuzzy or phonetic entity auto-merge; collisions return `entity_ambiguous`.
- Pure policy actions: `would_publish`, `review`, `discard`, `quarantine`.
- Confidence bands do not override impact or sensitivity.
- Finance, health, legal/identity, credential and external-action overrides.
- Secret-like values, missing provenance and tool instructions fail closed.
- The low-risk allowlist remains shadow-only as `would_publish`.
- Private append-only JSONL review events with strict replay.
- Candidate-fingerprint deduplication and one terminal decision per item.
- List/show/approve/reject/edit CLI; all responses preserve `vault_writes: false`.
- Edited approval records before/after hashes and cannot change candidate fields.
- Review directory/file permissions are enforced as `0700` / `0600`.

## Verification

- Python unit tests: 64 passed.
- Python bytecode compilation passed.
- Scoped Ruff 0.16.8 passed for all Phase 4 changed Python files.
- `hermes plugins doctor . --ci` passed discovery, import and registration with
  zero tools and zero hooks.
- Wheel build passed and contains entity, policy, review modules and
  `nexus/templates/review.md`.
- High-impact finance/health cases produced zero `would_publish` outcomes.
- Duplicate person aliases produced zero automatic merges.
- Approve and edited-approval decisions replayed from the append-only event log.

## Remaining acceptance gates

- Review and commit this local diff; it is not pushed or installed yet.
- Inspect one real ChatGPT export; the adapter remains experimental.
- Expand the synthetic extraction holdout before broad model-quality claims.
- Keep canonical auto-publish disabled. Phase 5 Vault writer must independently
  validate approved candidates and pass atomic-write/path-boundary tests.
