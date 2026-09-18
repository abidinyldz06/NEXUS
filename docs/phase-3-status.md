# Phase 3 delivery status

Date: 2026-09-18

## Outcome

Phase 3 is implemented and live-validated in shadow mode. Deterministic
segmentation, tool-free structured extraction, strict provenance validation,
bounded retry and a frozen contract evaluation are present. The packaged frozen
holdout passed through the configured live provider/model without publishing or
persisting candidates.

ChatGPT support remains experimental until a real export shape is inspected.
The active Hermes profile is pinned to the accepted prompt-v2 merge commit
recorded below and enabled. The shadow run did not modify the Vault, private
state, cron jobs or backup; the gateway was restarted only to load the exact
installed plugin commit.

## Implemented

- Natural user-turn segmentation with deterministic fingerprints.
- One-turn overlap when the configured character budget permits it.
- Oversized turns are preserved and flagged instead of silently truncated.
- System/tool messages remain provenance metadata and are excluded from model input.
- Extraction JSON Schema v1 for memory, entity, relation, commitment and correction
  candidates.
- Every input span must be cited or explicitly ignored; unknown spans fail closed.
- Prompt-injection text stays inside a serialized untrusted-data envelope.
- `ctx.llm.complete_structured` integration through plugin-owned `nexus_extract`.
- No provider/model override and no filesystem, tool, notification or publish action.
- Maximum 1–3 bounded attempts with sanitized terminal failure.
- Provider/model/task/prompt/schema/segment/token audit metadata without raw content.
- Twelve-case frozen contract fixture covering all candidate kinds, durable and
  temporary statements, assistant-only claims, prompt injection, ambiguous time
  and high-risk user facts.
- Explicit `hermes nexus eval --shadow` safety gate for the packaged frozen
  fixture; no candidate content is persisted or printed.
- Provider, model, agent, prompt/schema version, fixture hash and token-usage
  audit summary for live shadow runs.
- Transparent contract-stub baseline; it is not presented as model-quality evidence.

## Verification

- Hermes Python 3.11: 47 unit tests passed.
- Python bytecode compilation passed.
- NEXUS record and extraction JSON Schemas passed Draft 2020-12 meta-validation.
- `hermes plugins doctor . --ci` passed discovery, import and registration.
- Clean wheel build passed and includes all nested packages, `prompt_v2.txt` and the
  packaged frozen holdout fixture.
- Expanded contract holdout: 12 cases, 12 segments, provenance 100%,
  expected-kind recall/precision 100%, exact-case match 100%, empty-case
  precision 100% and schema failures 0 using a deterministic stub.
- A deliberately over-extracting test now fails expected-kind precision,
  exact-case match and empty-case precision instead of passing on recall alone.
- Live shadow holdout on `ollama-cloud` / `glm-5.3`: 2 cases, 2 segments,
  provenance 100%, expected-kind recall 100%, empty instruction-like case 100%,
  schema failures 0, 4,906 total tokens. Installed source commit:
  `bd0cb5aff63081ae3e868e87ecf3466aa96b9c91`.
- The live result is recorded in `eval/baseline-phase3-live-shadow.json` without
  candidate statements or source content.
- The first expanded run with prompt v1 failed closed at recall 88.89%,
  precision 66.67% and exact-case 66.67%; no writes or publication occurred.
- Prompt v2 kept the fixture and thresholds unchanged and passed the 12-case
  live shadow on `ollama-cloud` / `glm-5.3-flash`: recall 100%, precision 90%,
  exact-case 91.67%, empty-case precision/provenance 100%, schema failures 0 and
  21,189 total tokens. Installed source commit:
  `6dc8d5d5b8644cb8807c7902285786aba9ed15ee`.
- The expanded result is recorded in
  `eval/baseline-phase3-expanded-live-shadow.json` using aggregate/audit metadata
  only; `writes_performed=false` and `candidates_published=false`.
- Invalid spans, uncovered spans, malformed output and provider failures fail closed.

## Remaining acceptance gates

- Inspect one real ChatGPT export and rerun the source-to-segment pipeline.
- The expanded synthetic set remains smaller than the planned private golden
  dataset and is not by itself full real-world model-quality acceptance.
- Keep auto-publish disabled; Phase 4 policy/review must not be started implicitly.
