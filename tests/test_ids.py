from __future__ import annotations

import unittest

from nexus.ids import IdPrefix, is_nexus_id, new_id


class IdTests(unittest.TestCase):
    def test_new_id_is_valid_and_unique(self) -> None:
        first = new_id(IdPrefix.MEMORY)
        second = new_id(IdPrefix.MEMORY)

        self.assertNotEqual(first, second)
        self.assertTrue(is_nexus_id(first, IdPrefix.MEMORY))
        self.assertFalse(is_nexus_id(first, IdPrefix.SOURCE))

    def test_new_id_rejects_plain_string_prefix(self) -> None:
        with self.assertRaises(TypeError):
            new_id("mem")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
