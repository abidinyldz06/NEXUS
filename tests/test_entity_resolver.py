from __future__ import annotations

import unittest

from nexus.contracts import Entity, EntityType
from nexus.entity import EntityResolver, ResolutionStatus
from nexus.ids import IdPrefix, new_id


def entity(
    name: str,
    *,
    entity_type: EntityType = EntityType.PERSON,
    aliases: tuple[str, ...] = (),
    linked_notes: tuple[str, ...] = (),
) -> Entity:
    return Entity(
        id=new_id(IdPrefix.ENTITY),
        type=entity_type,
        display_name=name,
        normalized_name=name.casefold(),
        aliases=aliases,
        linked_notes=linked_notes,
    )


class EntityResolverTests(unittest.TestCase):
    def test_exact_typed_alias_matches_without_fuzzy_matching(self) -> None:
        bahar = entity("Bahar Yıldız", aliases=("Bahar",))
        resolver = EntityResolver((bahar,))

        match = resolver.resolve(entity_type=EntityType.PERSON, mention="  BAHAR ")
        fuzzy = resolver.resolve(entity_type=EntityType.PERSON, mention="Bahaar")

        self.assertEqual(ResolutionStatus.MATCHED, match.status)
        self.assertEqual(bahar.id, match.entity_id)
        self.assertEqual(ResolutionStatus.NEW, fuzzy.status)
        self.assertEqual(
            ResolutionStatus.NEW,
            resolver.resolve(entity_type=EntityType.PERSON, mention="   ").status,
        )

    def test_person_collision_is_ambiguous_and_never_auto_merged(self) -> None:
        first = entity("Ahmet Bir", aliases=("Ahmet",))
        second = entity("Ahmet İki", aliases=("Ahmet",))
        result = EntityResolver((first, second)).resolve(
            entity_type=EntityType.PERSON, mention="Ahmet"
        )

        self.assertEqual(ResolutionStatus.AMBIGUOUS, result.status)
        self.assertIsNone(result.entity_id)
        self.assertEqual(tuple(sorted((first.id, second.id))), result.candidate_ids)

    def test_explicit_id_must_exist_and_have_the_requested_type(self) -> None:
        project = entity("NEXUS", entity_type=EntityType.PROJECT)
        result = EntityResolver((project,)).resolve(
            entity_type=EntityType.PERSON,
            mention="NEXUS",
            stable_id=project.id,
        )

        self.assertEqual(ResolutionStatus.INVALID_REFERENCE, result.status)

    def test_one_exact_linked_note_is_a_strong_match(self) -> None:
        vehicle = entity(
            "Fabia",
            entity_type=EntityType.ASSET,
            linked_notes=("Araçlar/Fabia.md",),
        )
        result = EntityResolver((vehicle,)).resolve(
            entity_type=EntityType.ASSET,
            mention="Araba",
            linked_note="Araçlar/Fabia.md",
        )

        self.assertEqual(ResolutionStatus.MATCHED, result.status)
        self.assertEqual(vehicle.id, result.entity_id)


if __name__ == "__main__":
    unittest.main()
