# Phase 0–1 delivery status

Date: 2026-09-16

## Outcome

Phase 1 is implemented locally on `codex/nexus-v0.1-phase-0-1`. NEXUS is a
discoverable standalone Hermes plugin with a read-only CLI, fail-closed config,
versioned Python contracts and a JSON Schema v1 contract.

The active Hermes installation, Obsidian Vault, gateway, cron jobs, backup and
user configuration were not modified.

## Verification

- Hermes Python 3.11: 19 unit tests passed.
- Python bytecode compilation passed.
- `hermes plugins doctor . --ci` passed real discovery, import and registration.
- A temporary `HERMES_HOME` discovered and enabled `nexus` 0.1.0.
- In that temporary home, `hermes nexus status --json` and
  `hermes nexus config validate --json` returned `ok: true` and
  `write_enabled: false`.
- Plugin Doctor reported zero tool and zero hook registrations.

## Phase boundary

Completed locally:

- Architecture, security and ADR baselines.
- Sensitive auto-publish deny-by-default policy.
- Plugin manifest and namespaced auxiliary task registration.
- Read-only status/config validation CLI.
- Stable opaque IDs and deterministic serialization.
- Provenance-required record contracts and JSON Schema v1.

Still required before Phase 0 can be marked complete:

- Validate one suitable real ChatGPT export shape without committing private
  content.
- Create the initial local baseline commit after review.
- Defer the Vault git-dir canary until a later phase actually writes canonical
  notes.

Phase 2 must not claim ChatGPT parser acceptance until the real export shape is
available. Hermes and manual source adapters may use redacted fixtures, but the
real ChatGPT format remains a separate acceptance gate.
