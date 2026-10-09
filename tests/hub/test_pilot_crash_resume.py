"""Real process interruption, with a fake provider and disposable data only."""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from nexus.hub import operation_status, pilot
from nexus.hub.budget import BudgetError


class PilotCrashResumeTests(TestCase):
    def test_process_exit_preserves_hold_and_does_not_dispatch_again(self):
        model = "stealth/space-bunny-alpha"
        catalog = {"data": [{"id": model, "pricing": {"prompt": "0", "completion": "0"}}]}
        identifier = str(uuid4())
        with TemporaryDirectory(dir=Path(gettempdir()).resolve()) as directory:
            root = Path(directory)
            child = subprocess.Popen(
                [sys.executable, "-u", "-c", """
import sys, threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from nexus.hub import pilot
root, identifier = Path(sys.argv[1]), sys.argv[2]
model = "stealth/space-bunny-alpha"
catalog = {"data": [{"id": model, "pricing": {"prompt": "0", "completion": "0"}}]}
def transport(*args):
    print("PROVIDER_STARTED", flush=True)
    threading.Event().wait()
with patch.object(pilot.free_model, "read_catalog", return_value=catalog), \
     patch.object(pilot.providers, "_credentials", return_value={"api_key": "sk-or-synthetic"}), \
     patch.object(pilot.free_model, "_transport", side_effect=transport):
    pilot.run(SimpleNamespace(data_path=root, auto_publish_enabled=False),
              request_id=identifier, model=model)
""", directory, identifier],
                cwd=Path(__file__).resolve().parents[2],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                # A bounded readiness wait avoids hanging CI if the child fails before dispatch.
                import selectors

                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=10), "provider did not start")
                    self.assertEqual("PROVIDER_STARTED", child.stdout.readline().strip())
                child.terminate()
                child.communicate(timeout=10)
                config = SimpleNamespace(data_path=root, auto_publish_enabled=False)
                state = operation_status.snapshot(config)
                self.assertTrue(state["blocked"])
                self.assertEqual("unknown", state["items"][0]["state"])
                self.assertFalse(state["items"][0]["cost_verified"])
                with patch.object(pilot.free_model, "read_catalog", return_value=catalog), \
                     patch.object(pilot.providers, "_credentials", return_value={"api_key": "sk-or-synthetic"}), \
                     patch.object(pilot.free_model, "_transport") as transport:
                    repeated = pilot.run(config, request_id=identifier, model=model)
                    self.assertEqual("already_recorded", repeated["status"])
                    self.assertFalse(repeated["inference_attempted"])
                    with self.assertRaises(BudgetError):
                        pilot.run(config, request_id=str(uuid4()), model=model)
                    transport.assert_not_called()
                self.assertEqual(1, operation_status.snapshot(config)["total"])
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)
