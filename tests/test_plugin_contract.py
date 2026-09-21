from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any


class FakeContext:
    def __init__(self) -> None:
        self.auxiliary: list[tuple[str, dict[str, Any]]] = []
        self.commands: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []

    def register_auxiliary_task(self, key: str, **kwargs: Any) -> None:
        self.auxiliary.append((key, kwargs))

    def register_cli_command(self, **kwargs: Any) -> None:
        self.commands.append(kwargs)

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks.append((name, callback))

    def get_config(self, key: str, default: object = None) -> object:
        return default


class PluginContractTests(unittest.TestCase):
    def test_manifest_stays_compatible_with_the_active_hermes_installer(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = (root / "plugin.yaml").read_text(encoding="utf-8")

        self.assertIn("manifest_version: 1", manifest)
        self.assertIn("api_version: 1", manifest)

    def test_registers_one_cli_and_namespaced_auxiliary_task(self) -> None:
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "nexus_plugin_entry",
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        context = FakeContext()

        module.register(context)

        self.assertEqual("nexus_extract", context.auxiliary[0][0])
        self.assertEqual("nexus_route", context.auxiliary[1][0])
        self.assertEqual("nexus", context.commands[0]["name"])
        self.assertEqual(1, len(context.commands))
        self.assertEqual(2, len(context.auxiliary))
        self.assertEqual(1, len(context.hooks))
        self.assertEqual("pre_llm_call", context.hooks[0][0])

    def test_pre_llm_hook_injects_route_metadata_without_source_text(self) -> None:
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(
            "nexus_plugin_entry_hook",
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(module)
        context = FakeContext()
        module.register(context)
        callback = context.hooks[0][1]
        source = "Müşteri yarın pasaportunu getirecek"

        injected = callback(user_message=source)

        assert isinstance(injected, dict)
        context_text = injected["context"]
        self.assertIn("category=customer_or_crm", context_text)
        self.assertIn("would_execute=false", context_text)
        self.assertIn("needs_human_review=true", context_text)
        self.assertNotIn("pasaport", context_text)
        self.assertNotIn(source, context_text)


if __name__ == "__main__":
    unittest.main()
