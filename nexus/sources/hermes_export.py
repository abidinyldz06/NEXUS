"""Safe wrapper around Hermes's official redacted JSONL export command."""

from __future__ import annotations

import os
import stat
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
    parent_stat = output.parent.stat()
    if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise HermesExportError("Hermes export parent must be owner-only")
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
    output = output_path.expanduser()
    command = build_export_command(output, session_id=session_id, executable=executable)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            umask=0o077,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HermesExportError("Hermes session export failed to start or timed out") from exc
    if result.returncode != 0:
        raise HermesExportError(f"Hermes session export failed with exit code {result.returncode}")
    if not output.is_file() or output.is_symlink():
        raise HermesExportError("Hermes reported success but no safe JSONL output was created")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(output, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise HermesExportError("Hermes export output must be a regular file")
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)
    except OSError as exc:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise HermesExportError("Hermes export output could not be secured") from exc
    return output
