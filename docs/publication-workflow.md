# Approved memory, entity, relation and commitment publication workflow

This workflow is the only v0.1 path from a human-approved review item to a
canonical memory, entity, relation or commitment record. It does not enable
auto-publish.

## Eligibility

A review item must be `approved` or `edited` and carry a valid approval decision.
Memory candidates are closed to these fields:

- required: `statement`, `memory_type`, `confidence`, `impact`
- optional: `entity_ids`, `extractor`

Source references come from the review item and cannot be replaced by candidate
JSON. Every `entity_id` must already exist as a canonical entity. The canonical
memory ID is deterministically derived from the review ID, so retries cannot
create a second record.

Commitment candidates use one closed shape containing `statement`,
`actor_entity_id`, `confidence`, `impact`, `timezone`, `due_date`, `due_time`,
`due_precision`, `target_entity_ids`, `notify` and `extractor`. Staging leaves
the actor unresolved and never enables notification automatically; an operator
must edit the existing fields to complete the candidate. Actor and target IDs
must already exist as canonical entities. The commitment ID is deterministically
derived from the review ID.

Relation candidates use one closed shape containing `statement`,
`from_entity_id`, `predicate`, `to_entity_id`, `literal`, `confidence`, `impact`
and `extractor`. Staging leaves both entity ends and the predicate unresolved.
Publication requires existing canonical entity IDs, one target form, and an
allowlisted predicate (`works_at`, `owns`, `related_to`, `has_role`). Literal
targets are limited to `has_role`. An existing identical active relation blocks
a duplicate canonical write.

Entity candidates use one closed shape containing `display_name`,
`normalized_name`, `entity_type`, `aliases`, `linked_notes` and `extractor`.
Staging leaves `entity_type` unresolved. Publication requires normalized name
parity with the display name and rejects an exact name/alias or linked-note
collision with an existing entity of the same type. The canonical entity ID is
deterministically derived from the review ID.

## Safe sequence

```bash
hermes nexus review publish REV_ID --dry-run
hermes nexus review publish REV_ID --apply --confirm REV_ID
```

Dry-run validates the review decision, candidate contract, target identity,
source/entity references and any existing publication state without writing.
Apply repeats those checks and requires an exact review-ID confirmation.

A successful initial apply:

1. atomically writes the canonical record; memory publication also updates the
   generated Current-Memory view while entity/relation/commitment publication does not,
2. rebuilds the disposable SQLite index,
3. appends a content-free publication event to the private review log.

Reapplying the same fully recorded publication performs no writes. Conflicting
canonical content or a publication audit that disagrees with canonical state
fails closed.

## Failure recovery

- Vault transaction failure leaves the canonical record and any generated view
  unchanged.
- Index rebuild failure removes the newly created record, restores the previous
  view bytes and verifies that the prior index was preserved.
- If the private review audit fails after canonical/index commit, the command
  reports an incomplete audit and does not claim rollback. Repeat the exact
  apply command. The retry verifies the deterministic canonical payload,
  rebuilds the derived index and appends only the missing review audit.
- A concurrent target or applicable view change makes rollback fail closed instead of
  overwriting the concurrent bytes.

## Production gate

Source tests use only temporary synthetic Vaults. A real production apply must
name one reviewed target and receive target-specific operational approval after
its dry-run output is inspected. `write_enabled` and `auto_publish_enabled`
remain false for unattended flows.
