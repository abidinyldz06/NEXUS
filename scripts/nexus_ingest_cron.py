#!/usr/bin/env python3
"""Read-only cron probe for Inbox parse failures; successful runs stay silent."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys


def main() -> int:
    hermes = shutil.which("hermes")
    if hermes is None:
        print("NEXUS ingest probe error: hermes executable is unavailable", file=sys.stderr)
        return 2
    try:
        completed = subprocess.run(
            [hermes, "nexus", "ingest", "--dry-run", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("NEXUS ingest probe failed", file=sys.stderr)
        return 2
    if completed.returncode != 0:
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        print("NEXUS ingest probe failed", file=sys.stderr)
        return completed.returncode
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        print("NEXUS ingest probe returned invalid JSON", file=sys.stderr)
        return 2
    rejected = payload.get("summary", {}).get("rejected", 0)
    errors = payload.get("errors", [])
    if rejected or errors:
        print(f"NEXUS ingest probe: rejected={rejected}, errors={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
