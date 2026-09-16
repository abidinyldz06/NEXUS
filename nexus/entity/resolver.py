"""Fail-closed entity resolver for Phase 4."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from ..contracts import Entity, EntityType


class ResolutionStatus(StrEnum):
    MATCHED = "matched"
    NEW = "new"
    AMBIGUOUS = "ambiguous"
    INVALID_REFERENCE = "invalid_reference"


def normalize_alias(value: str) -> str:
    """Normalize spelling without applying fuzzy or phonetic matching."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@dataclass(frozen=True, slots=True)
class EntityResolution:
    status: ResolutionStatus
    entity_id: str | None
    candidate_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


class EntityResolver:
    """Resolve only explicit IDs, exact typed aliases, or one exact linked note."""

    def __init__(self, entities: Iterable[Entity]) -> None:
        self._entities = tuple(entities)
        self._by_id = {entity.id: entity for entity in self._entities}

    def resolve(
        self,
        *,
        entity_type: EntityType,
        mention: str,
        stable_id: str | None = None,
        linked_note: str | None = None,
    ) -> EntityResolution:
        if stable_id is not None:
            entity = self._by_id.get(stable_id)
            if entity is None or entity.type is not entity_type:
                return EntityResolution(
                    ResolutionStatus.INVALID_REFERENCE,
                    None,
                    (),
                    ("entity_reference_invalid",),
                )
            return EntityResolution(
                ResolutionStatus.MATCHED,
                entity.id,
                (entity.id,),
                ("stable_id_match",),
            )

        normalized = normalize_alias(mention)
        alias_matches = tuple(
            entity.id
            for entity in self._entities
            if entity.type is entity_type
            and bool(normalized)
            and normalized
            in {
                normalize_alias(entity.display_name),
                normalize_alias(entity.normalized_name),
                *(normalize_alias(alias) for alias in entity.aliases),
            }
        )
        if len(alias_matches) == 1:
            return EntityResolution(
                ResolutionStatus.MATCHED,
                alias_matches[0],
                alias_matches,
                ("exact_alias_match",),
            )
        if len(alias_matches) > 1:
            return EntityResolution(
                ResolutionStatus.AMBIGUOUS,
                None,
                tuple(sorted(alias_matches)),
                ("entity_ambiguous",),
            )

        if linked_note:
            note_matches = tuple(
                entity.id
                for entity in self._entities
                if entity.type is entity_type and linked_note in entity.linked_notes
            )
            if len(note_matches) == 1:
                return EntityResolution(
                    ResolutionStatus.MATCHED,
                    note_matches[0],
                    note_matches,
                    ("exact_linked_note_match",),
                )
            if len(note_matches) > 1:
                return EntityResolution(
                    ResolutionStatus.AMBIGUOUS,
                    None,
                    tuple(sorted(note_matches)),
                    ("entity_ambiguous",),
                )

        return EntityResolution(ResolutionStatus.NEW, None, (), ("new_entity",))
