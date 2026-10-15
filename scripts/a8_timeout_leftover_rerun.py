#!/usr/bin/env python3
"""Print the nine A8 timeout leftovers. Does not call a model or write the vault."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

from nexus.sources.hermes import HermesAdapter

DATA = Path.home() / ".local/share/nexus-v2-pilot"
INBOX = DATA / "live-mirror-inbox"
CKPT = DATA / "ingest" / "v2" / "checkpoints"
CHAR_CAP = 12_000


def failed_rows() -> list[dict]:
    rows: list[dict] = []
    if not CKPT.is_dir():
        return rows
    for path in sorted(CKPT.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for segment_id, item in (payload.get("segments") or {}).items():
            if not isinstance(item, dict) or item.get("status") != "FAILED_SEGMENT":
                continue
            rows.append(
                {
                    "segment_id": str(segment_id),
                    "conversation_id": item.get("conversation_id"),
                    "ingest_id": item.get("ingest_id") or path.stem,
                    "start": item.get("start_message_index"),
                    "end": item.get("end_message_index"),
                    "attempts": item.get("attempt_count"),
                    "failure_class": item.get("failure_class"),
                    "split_fallback": bool(item.get("split_fallback")),
                    "timeout_count": (item.get("extraction") or {}).get("timeout_count"),
                }
            )
    return rows


def _conversations() -> dict:
    adapter = HermesAdapter()
    found = {}
    if not INBOX.is_dir():
        return found
    for path in sorted(INBOX.glob("*.jsonl")):
        try:
            pack = adapter.parse_bytes(path.read_bytes(), original_name=path.name)
        except Exception:
            continue
        if not pack.conversations:
            continue
        conversation = pack.conversations[0]
        found[conversation.external_conversation_id] = (path, conversation)
    return found


def classify(rows: list[dict] | None = None) -> list[dict]:
    rows = failed_rows() if rows is None else rows
    sources = _conversations()
    classified = []
    for row in rows:
        source = sources.get(row.get("conversation_id"))
        chars = None
        if source is not None:
            _path, conversation = source
            start = int(row.get("start") or 0)
            end = int(row.get("end") or start)
            messages = conversation.messages[start : end + 1]
            chars = sum(len(message.content_text or "") for message in messages)
        if source is None:
            kind = "source_missing"
        elif chars is not None and chars > CHAR_CAP:
            kind = "oversized_turn"
        elif int(row.get("attempts") or 0) < 3:
            kind = "retry_not_exhausted"
        else:
            kind = "provider_slow_retry_exhausted"
        classified.append({**row, "chars": chars, "class": kind})
    return classified


def planned_jobs(classified: list[dict] | None = None) -> list[dict]:
    """Job list for a later approved shadow rerun. Hashes only; no execution."""
    classified = classify() if classified is None else classified
    sources = _conversations()
    jobs = []
    seen: set[tuple[str, int, int]] = set()
    for row in classified:
        if row["class"] == "source_missing":
            continue
        key = (
            str(row.get("conversation_id")),
            int(row.get("start") or 0),
            int(row.get("end") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        path, _conversation = sources[row["conversation_id"]]
        jobs.append(
            {
                "relative_path": path.name,
                "content_sha256": sha256(path.read_bytes()).hexdigest(),
                "conversation_id": row["conversation_id"],
                "span": [row.get("start"), row.get("end")],
                "class": row["class"],
                "command": [
                    "hermes",
                    "nexus",
                    "ingest",
                    "--shadow",
                    "--json",
                    "--source",
                    path.name,
                    "--confirm-sha",
                    "<sha256>",
                    "--conversation",
                    str(row["conversation_id"]),
                ],
            }
        )
    return jobs


def main() -> int:
    if "--execute" in sys.argv:
        print(
            json.dumps(
                {
                    "rerun": "blocked",
                    "reason": "this script only prints the plan; it does not launch ingest",
                }
            )
        )
        return 2
    payload = {
        "rerun": "blocked",
        "model_calls": False,
        "segments": classify(),
        "jobs": planned_jobs(),
        "proposed_budget": {
            "target_timeout_seconds": 120,
            "hard_timeout_seconds": 150,
            "applied": False,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
