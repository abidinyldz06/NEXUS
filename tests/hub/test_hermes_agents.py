import sys
from types import ModuleType
from unittest import TestCase
from unittest.mock import Mock, patch

from nexus.hub import hermes_agents


class HermesAgentTests(TestCase):
    def host(self, names):
        host = ModuleType("hermes_cli")
        profiles = ModuleType("hermes_cli.profiles")
        profiles.list_profile_names = Mock(return_value=names)
        profiles.list_profiles = Mock(side_effect=AssertionError("must not read or migrate configs"))
        return patch.dict(sys.modules, {"hermes_cli": host, "hermes_cli.profiles": profiles}), profiles

    def test_existing_only_links_no_creation_or_config_reads(self):
        context, profiles = self.host(["default", "writer-agent", "unrelated-private-profile"])
        with context:
            result = hermes_agents.snapshot()
        self.assertTrue(result["read_only"])
        self.assertFalse(result["dispatch_enabled"])
        self.assertEqual(6, len(result["items"]))
        writer = next(row for row in result["items"] if row["profile"] == "writer-agent")
        self.assertEqual("/chat?profile=writer-agent", writer["chat_url"])
        coder = next(row for row in result["items"] if row["profile"] == "coder-agent")
        self.assertFalse(coder["present"])
        self.assertIsNone(coder["chat_url"])
        self.assertNotIn("unrelated-private-profile", str(result))
        profiles.list_profile_names.assert_called_once_with()
        profiles.list_profiles.assert_not_called()

    def test_failure_is_sanitized_without_fake_success(self):
        context, profiles = self.host([])
        profiles.list_profile_names.side_effect = RuntimeError("private-path-and-secret")
        with context:
            result = hermes_agents.snapshot()
        self.assertFalse(result["available"])
        self.assertEqual([], result["items"])
        self.assertNotIn("private-path-and-secret", str(result))

    def test_invalid_names_cannot_create_external_links(self):
        context, profiles = self.host([None])
        with context:
            self.assertFalse(hermes_agents.snapshot()["available"])
        context, profiles = self.host(["default", "https://other.example", "../bad"])
        with context:
            result = hermes_agents.snapshot()
        self.assertEqual(["/chat?profile=default"],
                         [row["chat_url"] for row in result["items"] if row["chat_url"]])
