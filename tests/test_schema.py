from __future__ import annotations

import json
import unittest
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "nexus-v1.schema.json"


class JsonSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_is_versioned_draft_2020_12(self) -> None:
        self.assertEqual(
            "https://json-schema.org/draft/2020-12/schema", self.schema["$schema"]
        )
        self.assertTrue(self.schema["$id"].endswith("nexus-v1.schema.json"))

    def test_all_canonical_records_are_closed_and_versioned(self) -> None:
        definitions = self.schema["$defs"]
        for name in ("source", "memory", "entity", "relation", "commitment", "reviewItem"):
            with self.subTest(name=name):
                definition = definitions[name]
                self.assertFalse(definition["additionalProperties"])
                self.assertIn("schema_version", definition["required"])
                self.assertEqual(
                    {"$ref": "#/$defs/schemaVersion"},
                    definition["properties"]["schema_version"],
                )

    def test_provenance_is_required_for_derived_records(self) -> None:
        definitions = self.schema["$defs"]
        for name in ("memory", "relation", "commitment", "reviewItem"):
            with self.subTest(name=name):
                source_refs = definitions[name]["properties"]["source_refs"]
                self.assertEqual(1, source_refs["minItems"])


if __name__ == "__main__":
    unittest.main()
