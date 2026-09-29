from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from nexus.config import NexusConfig
from nexus.contracts import Impact, Memory, MemoryType, ReviewStatus, SourceRef
from nexus.ids import IdPrefix, new_id
from nexus.index import rebuild_index
from nexus.vault import VaultRepository

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # The plugin runs in Hermes, which supplies FastAPI.
    FastAPI = None
    TestClient = None


@unittest.skipIf(FastAPI is None, "FastAPI is supplied by the Hermes runtime")
class DashboardApiTests(unittest.TestCase):
    def test_get_routes_expose_bounded_read_only_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            vault.mkdir()
            data = root / "private"
            ref = SourceRef(
                source_id=new_id(IdPrefix.SOURCE),
                conversation_id="synthetic",
                span_ids=("message-1",),
                span_sha256=sha256(b"message-1").hexdigest(),
                excerpt="Seçili NEXUS kaynak alıntısı",
            )
            item = Memory(
                id=new_id(IdPrefix.MEMORY),
                type=MemoryType.FACT,
                summary="NEXUS Hub denemesi",
                source_refs=(ref,),
                confidence=0.9,
                impact=Impact.LOW,
                review_status=ReviewStatus.APPROVED,
            )
            VaultRepository(vault).commit_records((item,), run_id=new_id(IdPrefix.RUN))
            rebuild_index(vault, data / "nexus.db")
            config = NexusConfig.from_mapping({"vault_path": str(vault), "data_path": str(data)})
            before = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}

            module_name = "nexus_hub_dashboard_api_test"
            api_path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
            spec = importlib.util.spec_from_file_location(module_name, api_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            self.addCleanup(sys.modules.pop, module_name, None)
            spec.loader.exec_module(module)
            app = FastAPI()
            app.include_router(module.router, prefix="/api/plugins/nexus")
            with patch.object(module, "_settings", return_value=config), TestClient(app) as client:
                base = "/api/plugins/nexus/hub"
                self.assertEqual(1, client.get(base + "/overview").json()["index"]["records"])
                found = client.get(base + "/search", params={"q": "NEXUS"})
                self.assertEqual(item.id, found.json()["items"][0]["id"])
                self.assertTrue(
                    client.get(base + "/records/" + item.id).json()["canonical_verified"]
                )
                self.assertEqual([], client.get(base + "/reviews").json()["items"])
                self.assertEqual(405, client.post(base + "/overview").status_code)
            after = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_task_routes_save_one_draft_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "private"
            config = NexusConfig.from_mapping({"data_path": str(data)})
            module_name = "nexus_hub_dashboard_task_api_test"
            api_path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
            spec = importlib.util.spec_from_file_location(module_name, api_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            self.addCleanup(sys.modules.pop, module_name, None)
            spec.loader.exec_module(module)
            app = FastAPI()
            app.include_router(module.router, prefix="/api/plugins/nexus")
            body = {
                "idempotency_key": str(uuid4()),
                "title": "Kaynakları araştır",
                "goal": "Seçili konuyu incele",
                "expected_output": "Kaynaklı özet",
                "target_app": "Hermes",
                "data_class": "local_only",
                "hermes_session_id": "session_12345678",
            }
            with patch.object(module, "_settings", return_value=config), TestClient(app) as client:
                base = "/api/plugins/nexus/hub/tasks"
                self.assertEqual(409, client.get(base).status_code)
                self.assertEqual([], client.get(base + "?profile=default").json()["items"])
                self.assertFalse(data.exists())
                self.assertEqual(409, client.post(base, json=body).status_code)
                self.assertEqual(
                    409, client.post(base + "?profile=research-agent", json=body).status_code
                )
                self.assertFalse(data.exists())
                first = client.post(base + "?profile=default", json=body)
                self.assertEqual(200, first.status_code)
                self.assertTrue(first.json()["created"])
                self.assertFalse(first.json()["dispatched"])
                self.assertEqual("session_12345678", first.json()["task"]["hermes_session_id"])
                self.assertEqual("local_only", first.json()["task"]["data_class"])
                self.assertFalse(first.json()["task"]["hermes_reference_verified"])
                second = client.post(base + "?profile=default", json=body)
                self.assertEqual(200, second.status_code)
                self.assertFalse(second.json()["created"])
                self.assertEqual(first.json()["task"]["id"], second.json()["task"]["id"])
                self.assertEqual(1, client.get(base + "?profile=default").json()["total"])

    def test_provider_usage_requires_explicit_default_profile_action(self) -> None:
        module_name = "nexus_hub_dashboard_provider_api_test"
        api_path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(module_name, api_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router, prefix="/api/plugins/nexus")
        path = "/api/plugins/nexus/hub/providers/openrouter/usage"
        with patch.object(module, "_settings", side_effect=AssertionError("settings read")):
            with patch.object(module._providers, "snapshot", return_value={
                "provider": "openrouter", "status": "not_configured",
                "metrics": None, "inference_called": False,
            }) as usage, TestClient(app) as client:
                self.assertEqual(405, client.get(path + "?profile=default").status_code)
                self.assertEqual(409, client.post(path).status_code)
                self.assertEqual(409, client.post(path + "?profile=other").status_code)
                usage.assert_not_called()
                result = client.post(path + "?profile=default")
                self.assertEqual(200, result.status_code)
                self.assertFalse(result.json()["inference_called"])
                usage.assert_called_once_with("openrouter")
            with TestClient(app) as client:
                self.assertEqual(400, client.post(
                    "/api/plugins/nexus/hub/providers/custom/usage?profile=default"
                ).status_code)

    def test_route_advice_is_local_non_dispatching_and_profile_scoped(self) -> None:
        module_name = "nexus_hub_dashboard_route_api_test"
        api_path = Path(__file__).resolve().parents[2] / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(module_name, api_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(module)
        app = FastAPI()
        app.include_router(module.router, prefix="/api/plugins/nexus")
        path = "/api/plugins/nexus/hub/route-advice"
        with patch.object(module, "_settings", side_effect=AssertionError("settings read")):
            with patch.object(
                module._tasks, "create_draft", side_effect=AssertionError("dispatch")
            ):
                with TestClient(app) as client:
                    payload = {"request_text": "Geçen konuşmada kararı bul"}
                    self.assertEqual(409, client.post(path, json=payload).status_code)
                    self.assertEqual(
                        409, client.post(path + "?profile=other", json=payload).status_code
                    )
                    result = client.post(path + "?profile=default", json=payload)
                    self.assertEqual(200, result.status_code)
                    self.assertEqual("NEXUS", result.json()["target_app"])
                    self.assertFalse(result.json()["execution_enabled"])
                    self.assertNotIn("request_text", result.json())
                    self.assertEqual(400, client.post(
                        path + "?profile=default", json={"request_text": "x" * 501}
                    ).status_code)


if __name__ == "__main__":
    unittest.main()
