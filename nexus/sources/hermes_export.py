"""Safe wrapper around Hermes's official redacted JSONL export command."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..errors import HermesExportError


def build_export_command(
    output_path: Path, *, session_id: str | None = None, executable: str = "hermes"
) -> tuple[str, ...]:
    output = output_path.expanduser()
    if not output.is_absolute():
        raise HermesExportError("Hermes export output must be an absolute path")
    if output.suffix.lower() != ".jsonl":
        raise HermesExportError("Hermes export output must use the .jsonl extension")
    if output.exists() or output.is_symlink():
        raise HermesExportError("Hermes export output already exists")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise HermesExportError("Hermes export parent must be an existing non-symlink directory")
    command = [executable, "sessions", "export", str(output), "--format", "jsonl", "--redact"]
    if session_id:
        command.extend(["--session-id", session_id])
    return tuple(command)


def export_sessions(
    output_path: Path,
    *,
    session_id: str | None = None,
    executable: str = "hermes",
    timeout_seconds: int = 300,
) -> Path:
    """Run official export without a shell; always request secret redaction."""
    command = build_export_command(output_path, session_id=session_id, executable=executable)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HermesExportError("Hermes session export failed to start or timed out") from exc
    if result.returncode != 0:
        raise HermesExportError(f"Hermes session export failed with exit code {result.returncode}")
    if not output_path.is_file() or output_path.is_symlink():
        raise HermesExportError("Hermes reported success but no safe JSONL output was created")
    return output_path
