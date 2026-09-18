# Private golden evaluation workflow

This workflow evaluates human-labeled, real examples without committing them or
printing their messages and expected labels. It never stages review candidates
or writes canonical Vault records.

## Storage boundary

Store one JSON fixture below the configured private data directory:

```text
<data_path>/eval/private/golden-v1.json
```

The filename must be a `.json` basename. NEXUS rejects path separators,
symlinks, missing/non-regular files, empty files, files larger than 5 MiB and a
SHA-256 mismatch. The private directory and fixture must be owned by the current
user with no group/world permissions and must remain outside Git.

## Fixture shape

Use the packaged frozen fixture as the schema reference. Each case has a stable
opaque ID, one or more normalized messages and human-labeled `expected_kinds`:

```json
{
  "fixture_version": 1,
  "dataset": "private-golden",
  "cases": [
    {
      "id": "case-001",
      "messages": [
        {"id": "message-001", "role": "user", "content": "REDACTED EXAMPLE"}
      ],
      "expected_kinds": ["memory"]
    }
  ]
}
```

Allowed expected kinds are `memory`, `entity`, `relation`, `commitment` and
`correction`. Use an empty list for a case that should produce no candidate.

## Exact shadow run

Compute the fixture digest locally, inspect it, then run the exact basename and
digest:

```bash
chmod 700 ~/.local/share/nexus/eval/private
chmod 600 ~/.local/share/nexus/eval/private/golden-v1.json
shasum -a 256 ~/.local/share/nexus/eval/private/golden-v1.json
hermes nexus eval --shadow \
  --private-dataset golden-v1.json \
  --confirm-sha SHA256 \
  --json
```

The report contains only aggregate metrics, provider/model audit fields, prompt
and fixture hashes, token counts and acceptance state. It never includes the
fixture path, case messages, expected labels or candidate statements.

## Acceptance boundary

A successful run is model-quality evidence only for the exact fixture hash,
prompt hash, provider and model in that report. It does not authorize
auto-publish, review staging, production Vault writes or Telegram delivery.
