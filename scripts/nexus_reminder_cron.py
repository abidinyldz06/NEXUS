#!/usr/bin/env python3
"""Hermes no-agent wrapper: empty stdout stays silent, output is delivered verbatim."""

from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    hermes = shutil.which("hermes")
    if hermes is None:
        print("NEXUS reminder error: hermes executable is unavailable", file=sys.stderr)
        return 2
    try:
        completed = subprocess.run(
            [hermes, "nexus", "reminders", "--emit-local"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        print("NEXUS reminder error: local scan failed", file=sys.stderr)
        return 2
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
