# ADR 0004: A8 leftover segment timeouts need a documented budget, not a silent one

Status: accepted (16 October 2026 — Abidin approved the documented raise; the Q4 plan's measurement trigger fired: first-attempt p95 82s exceeded the 60s target across 50+ segments). Code defaults now carry the accepted values: 120s target / 150s hard cap / 300s human-triggered long-unit (unchanged). This ADR is the record of the change; no silent drift. Reruns remain human-approved only.

## Evidence (2026-10-15, read-only)

`a8-pr48-remaining.json`: 51/57 conversations complete (89.5%). Checkpoint scan: 9 `FAILED_SEGMENT`, all `failure_class=timeout`, plus 23 `incomplete`. `leftover_timeout_class_count` 12 is a different set: ingest-log rows with status failed, at least 3 attempts, at least 3 timeouts, and duration >= 500s. Those are the historical long failures, not the 9 open checkpoint rows.

`nexus ingest status` reports path health. It does not list segment rows. The nine rows below are from `ingest/v2/checkpoints`. Character counts are lengths only; message text was not copied.

| Segment | Conversation | Span | Chars | Attempts | Timeouts | Split fallback | Class |
|---|---|---|---|---|---|---|---|
| 272c790d849e | 20260616_125755 | 3-3 | 4138 | 3 | 9 | yes | retry exhausted, provider slow |
| e8efeae66954 | same span as above | 3-3 | 4138 | 3 | 6 | yes | duplicate failed row |
| a4e413dcf3be | 20260622_150017 | 0-0 | 3098 | 3 | 12 | yes | retry exhausted, provider slow |
| 0ea988e7c7a5 | 20260905_210220 | 52-52 | 1923 | 3 | 3 | yes | retry exhausted, provider slow |
| 8024e508fe2b | same span as above | 52-52 | 1923 | 3 | 3 | yes | duplicate failed row |
| 51f5d00c046c | 20260618_085540 | 0-0 | 6918 | 3 | 12 | yes | retry exhausted, provider slow |
| e4daf61d9a9a | same span as above | 0-0 | 6918 | 3 | 12 | yes | duplicate failed row |
| 77fb3c3d7345 | 20260819_084741 | 0-0 | 4972 | 1 | 4 | yes | retry not exhausted |
| 28a4523dcb9d | 677d36c3-24d8 | 0-3 | source file absent | 3 | 3 | no | source missing; do not force |

Unique sourced turns: 5. All are a single extractable message under the 12_000 character segment cap. None is an unsplittable giant turn. First-attempt p95 on the acceptance file is 82.053s: above the 60s target, below the 90s hard cap.

## Decision requested

Do not raise `V2_TARGET_TIMEOUT_SECONDS` in code without this ADR being accepted. A silent bump is forbidden.

The fitting documented change is 60s to 120s, because the misses are provider time on ordinary single turns, not oversized units. `service_extractor` rejects a target above the hard cap, so 120s also requires raising `V2_HARD_TIMEOUT_SECONDS` from 90 to at least 150. Proposed config, still not applied:

```text
ingest_v2.target_timeout_seconds = 120
ingest_v2.hard_timeout_seconds = 150
ingest_v2.long_unit_budget_seconds = 300  # already exists; human-triggered only
```

The existing `--long-unit-budget` lane (default 300s, logged, only when `split_fallback` or `oversized_turn`) stays for genuinely oversized turns. Using it for these 2-7k character turns would spend a 300s lane on work whose observed p95 is 82s.

`20260819_084741` still has `attempt_count` 1. `677d36c3-24d8` has no inbox source; a rerun must skip it. Duplicate segment ids for the same span should not be ingested twice.

A8 GO remains unmet: completion 89.5% versus 95%, and `p95_lt_60` is false. `docs/a8-limited-use-decision.md` still governs unsupervised bulk ingest: limited human use is accepted, technical GO is not.

## Rerun

`scripts/a8_timeout_leftover_rerun.py` prints this diagnosis and the job list. It does not call Hermes, the extractor, or the vault. A later approved run would follow `a8-pr48-remaining.py` (`hermes nexus ingest --shadow`) only for the five sourced turns, with the budget change accepted first. That command is not executed by this change.
