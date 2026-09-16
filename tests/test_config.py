from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nexus.config import NexusConfig
from nexus.errors import ConfigurationError


class ConfigTests(unittest.TestCase):
    def test_defaults_are_fail_closed_for_writes(self) -> None:
        config = NexusConfig.from_mapping({})

        self.assertFalse(config.write_ready)
        self.assertFalse(config.auto_publish_enabled)
        self.assertFalse(config.sensitive_auto_publish)
        self.assertIn("vault_path is not configured", config.validate_existing_paths())

    def test_existing_vault_passes_read_only_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = NexusConfig.from_mapping({"vault_path": directory})
            self.assertEqual((), config.validate_existing_paths())

    def test_relative_paths_are_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            NexusConfig.from_mapping({"vault_path": "relative/vault"})

    def test_sensitive_auto_publish_is_rejected(self) -> None:
        with self.assertRaises(ConfigurationError):
            NexusConfig.from_mapping({"sensitive_auto_publish": True})

    def test_index_is_below_private_data_path(self) -> None:
        config = NexusConfig.from_mapping({"data_path": "/tmp/nexus-test-data"})
        self.assertEqual(Path("/tmp/nexus-test-data/nexus.db"), config.index_path)


if __name__ == "__main__":
    unittest.main()
