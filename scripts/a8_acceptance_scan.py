#!/usr/bin/env python3
"""Read-only A8 acceptance scan. Does not call a model or write the vault."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus.config import NexusConfig  # noqa: E402
from nexus.ingest_v2 import FAILED_SEGMENT, acceptance_report  # noqa: E402
from nexus.sources.hermes import HermesAdapter  # noqa: E402

DATA = Path.home() / ".local/share/nexus-v2-pilot"
INBOX = DATA / "live-mirror-inbox"
CKPT = DATA / "ingest" / "v2" / "checkpoints"
OUT = DATA / "a8-pr48-remaining.json"
VAULT = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/hermes-memory"
PLUGIN = Path.home() / ".hermes/plugins/nexus"
UNMATCHED_NOTE = "unmatched = source_missing, ADR 0004 gereği zorlanmaz"


def plugin_note(plugin_root: Path | None = None) -> str:
    """Installed checkout HEAD. Errors stay a note, not a crash."""
    root = PLUGIN if plugin_root is None else plugin_root
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not sha or any(char not in "0123456789abcdef" for char in sha):
        return "unknown"
    return f"installed {sha} shadow only"


def build_jobs(inbox: Path, checkpoints: Path) -> tuple[list[dict], int]:
    adapter = HermesAdapter()
    by_cid: dict[str, Path] = {}
    if inbox.is_dir():
        for path in sorted(inbox.glob("*.jsonl")):
            try:
                pack = adapter.parse_bytes(path.read_bytes(), original_name=path.name)
            except Exception:
                continue
            if pack.conversations:
                by_cid.setdefault(pack.conversations[0].external_conversation_id, path)
    jobs = []
    unmatched = 0
    if not checkpoints.is_dir():
        return jobs, unmatched
    for path in sorted(checkpoints.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        open_rows = [
            item
            for item in (payload.get("segments") or {}).values()
            if isinstance(item, dict) and item.get("status") in {FAILED_SEGMENT, "incomplete"}
        ]
        failed = [item for item in open_rows if item.get("status") == FAILED_SEGMENT]
        if not open_rows:
            continue
        cid = payload.get("conversation_id")
        src = by_cid.get(cid)
        if src is None:
            unmatched += 1
            continue
        jobs.append(
            {
                "relative_path": src.name,
                "content_sha256": sha256(src.read_bytes()).hexdigest(),
                "conversation_id": cid,
                "ingest_id": payload.get("ingest_id") or path.stem,
                "failed_n": len(failed),
                "open_n": len(open_rows),
            }
        )
    return jobs, unmatched


def scan(
    *,
    inbox: Path = INBOX,
    checkpoints: Path = CKPT,
    data_path: Path = DATA,
    vault_path: Path = VAULT,
    plugin_root: Path | None = None,
) -> dict:
    """Roll up acceptance counts. Checkpoints and the inbox are only read."""
    config = NexusConfig.from_mapping(
        {
            "data_path": str(data_path),
            "inbox_path": str(inbox),
            "vault_path": str(vault_path),
            "ingest_pipeline_v2": True,
            "auto_publish_enabled": False,
        }
    )
    report = acceptance_report(config)
    jobs, unmatched = build_jobs(inbox, checkpoints)
    now = datetime.now(timezone.utc).isoformat()
    summary = {
        "ok": True,
        "started": now,
        "finished": now,
        "plugin_note": plugin_note(plugin_root),
        "job_count": len(jobs),
        "unmatched": unmatched,
        "unmatched_note": UNMATCHED_NOTE if unmatched else None,
        "final_status": {},
        "ok_count": 0,
        "vault_write_any": False,
        "model_calls": False,
        "this_run_samples": 0,
        "this_run_p50_s": None,
        "this_run_p95_s": None,
        "this_run_completed_p95_s": None,
        "this_run_first_attempt_completed_p95_s": None,
        "this_run_min_s": None,
        "this_run_max_s": None,
        "this_run_status": {},
        "before_completed": report.get("completed_conversations"),
        "after_completed": report.get("completed_conversations"),
        "unique": report.get("unique_conversations"),
        "completion_pct": report.get("completion_pct"),
        "segment_status": report.get("segment_status"),
        "failed_segment_class": report.get("failed_segment_class"),
        "p95_segment_seconds": report.get("p95_segment_seconds"),
        "p95_excluding_leftover_seconds": report.get("p95_excluding_leftover_seconds"),
        "leftover_timeout_class_count": report.get("leftover_timeout_class_count"),
        "ledger_ids_not_in_vault": report.get("ledger_ids_not_in_vault"),
        "thresholds": report.get("thresholds"),
        "results": [],
    }
    return summary


def main() -> int:
    jobs, unmatched = build_jobs(INBOX, CKPT)
    print(
        json.dumps(
            {
                "phase": "start",
                "job_count": len(jobs),
                "unmatched": unmatched,
                "unmatched_note": UNMATCHED_NOTE if unmatched else None,
                "canary": False,
                "model_calls": False,
                "vault_writes": False,
            }
        ),
        flush=True,
    )
    summary = scan()
    OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    public = {key: summary[key] for key in summary if key != "results"}
    print(json.dumps({"phase": "done", **public}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
