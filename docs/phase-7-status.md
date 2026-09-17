# Phase 7 delivery status

Date: 2026-09-17

## Outcome

Phase 7 is implemented and locally validated on
`codex/nexus-phase7-commitments-pulse`. It adds deterministic commitment date
resolution and an output-only local reminder scanner without adding a notifier,
activating a cron job or sending a Telegram message.

No write was made to the configured production Obsidian Vault. Production has
no canonical commitments, and the active Hermes plugin remains on the merged
Phase 6 commit until this branch is reviewed and deliberately installed.

## Implemented

- Conservative Turkish resolution for explicit dates, today/tomorrow and
  weekday names using the source timestamp in `Europe/Istanbul`.
- Ambiguous relative dates remain unschedulable.
- Open/done/cancelled/overdue commitment lifecycle helpers.
- Due evaluation limited to approved, edited or auto-reviewed records with
  `notify=true`, non-ambiguous dates and no prior `notified_at`.
- Canonical `notified_at` update with content-hash preconditions and exact-byte
  rollback if the derived-index rebuild fails.
- Source-referenced local digest capped at 20 reminders per run.
- Hermes no-agent reminder wrapper: empty stdout is silent.
- Read-only ingestion probe wrapper that reports counts, never source text.
- `hermes nexus reminders --emit-local` explicit safety gate.

## Verification

- Python 3.11 unit tests: 93 passed.
- Monday-to-Friday and Istanbul timezone-boundary examples passed.
- Ambiguous and pending-review commitments were never scheduled.
- Reminder replay emitted once and persisted canonical `notified_at`.
- Injected post-write rebuild failure restored exact canonical bytes.
- A 21-item queue emitted bounded 20-item and 1-item digests without duplicates.
- Empty no-agent output stayed silent; wrapper commands used no shell.
- Scoped Ruff, bytecode compilation and diff whitespace checks passed.

## Remaining acceptance gates

- Review, commit, push and merge this branch; no PR exists yet.
- Install the exact merged commit and run an empty production local-output canary.
- Copy the fixed wrapper into Hermes's scripts directory and create only a
  paused/local no-agent cron job after separate approval.
- Complete a 7-day local-only canary before requesting Telegram delivery.
- A Telegram canary requires explicit approval and user-observed delivery; it is
  not accepted by unit tests or an HTTP response alone.
