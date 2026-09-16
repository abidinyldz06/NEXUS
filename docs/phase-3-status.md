# Phase 3 delivery status

Date: 2026-09-16

## Outcome

Phase 3 is implemented and live-validated in shadow mode. Deterministic
segmentation, tool-free structured extraction, strict provenance validation,
bounded retry and a frozen contract evaluation are present. The packaged frozen
holdout passed through the configured live provider/model without publishing or
persisting candidates.

ChatGPT support remains experimental until a real export shape is inspected.
The active Hermes profile now has the plugin pinned at the source commit recorded
below and enabled. Its only added NEXUS setting is the verified existing
`vault_path`. The Vault contents, gateway process, cron jobs and backup were not
modified; the gateway was not restarted.

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
- Frozen multi-turn and instruction-like-text contract fixture.
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
- Wheel build passed and includes all nested packages, `prompt_v1.txt` and the
  packaged frozen holdout fixture.
- Contract holdout: provenance 100%, expected-kind recall 100%, empty injection case
  100%, schema failures 0 using a deterministic stub.
- Live shadow holdout on `ollama-cloud` / `glm-5.3`: 2 cases, 2 segments,
  provenance 100%, expected-kind recall 100%, empty instruction-like case 100%,
  schema failures 0, 4,906 total tokens. Installed source commit:
  `bd0cb5aff63081ae3e868e87ecf3466aa96b9c91`.
- The live result is recorded in `eval/baseline-phase3-live-shadow.json` without
  candidate statements or source content.
- Invalid spans, uncovered spans, malformed output and provider failures fail closed.

## Remaining acceptance gates

- Inspect one real ChatGPT export and rerun the source-to-segment pipeline.
- Expand the current two-case synthetic contract holdout before treating it as
  broad model-quality evidence; it is sufficient for the Phase 3 contract gate,
  not the later full golden-dataset acceptance.
- Keep auto-publish disabled; Phase 4 policy/review must not be started implicitly.
