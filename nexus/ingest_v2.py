"""Segmented, resumable ingest. Flag off never reaches this module from CLI."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from .config import NexusConfig
from .contracts import (
    Impact,
    Memory,
    MemoryType,
    RecordStatus,
    ReviewStatus,
    SourceRef,
)
from .entity.resolver import normalize_alias
from .errors import ExtractionError, NexusError, NexusIndexError, ReviewStoreError, VaultError
from .extraction.schema import EXTRACTION_SCHEMA_VERSION, ExtractionCandidate, ExtractionResult
from .extraction.service import (
    ExtractionService,
    ExtractorBusy,
    classify_extraction_failure,
)
from .fingerprints import memory_fingerprint, stable_hash
from .index.rebuild import rebuild_index
from .normalize import NormalizedConversation, normalize_text
from .policy import contains_secret_value, ingest_write_disposition, redact_secrets
from .review import ReviewStore, create_review_item
from .segmenter import (
    DEFAULT_MAX_MESSAGES,
    DEFAULT_TARGET_CHARS,
    SEGMENT_ID_SCHEMA_VERSION,
    ConversationSegment,
    normalized_content_hash,
    segment_conversation_v2,
)
from .vault import VaultRepository
from .vault.rebuild_views import current_memory_view_write
from .vault.renderer import extract_record_payload, extract_written_at, memory_from_payload

V2_TARGET_TIMEOUT_SECONDS = 120
V2_HARD_TIMEOUT_SECONDS = 150
LONG_UNIT_DEFAULT_SECONDS = 300
MIN_SEGMENT_CHARS = 500
MAX_RETRIES = 2
MAX_ATTEMPTS = 1 + MAX_RETRIES
RETRY_BACKOFF_SECONDS = (1.0, 2.0)
CLAIM_SIMILARITY_THRESHOLD = 0.92
FAILED_SEGMENT = "FAILED_SEGMENT"
CARRY_FORWARD_CHARS = 240
CARRY_FORWARD_MARKER = "READONLY_PRIOR_SUMMARY"
CANARY_CONFIRM = "canary"
CANARY_DAILY_LIMIT = 25

_RETRYABLE = frozenset(
    {"timeout", "http_5xx", "transient_provider", "transient_transport"}
)
_NON_RETRYABLE = frozenset(
    {
        "http_4xx",
        "invalid_json",
        "schema_invalid",
        "provider_or_runtime",
        "scrubber_reject",
        "policy_reject",
        "validation",
        "structured_output",
    }
)

_OBSERVATION_KEYS = (
    "ingest_id",
    "conversation_id",
    "started_at",
    "finished_at",
    "schema_version",
    "status",
    "segment_count",
    "segment_id",
    "segment_range",
    "latency_ms",
    "retries",
    "token_estimate",
    "segment_status",
    "segment_duration_ms",
    "segment_wall_ms",
    "attempt_count",
    "retry_count",
    "timeout_count",
    "candidate_count",
    "accepted_count",
    "rejected_count",
    "duplicate_prevented_count",
    "duplicates_prevented",
    "scrubbed",
    "superseded_count",
    "writes",
    "written_files",
    "error_class",
    "errors",
    "long_unit",
    "final_status",
)


class IngestV2Error(NexusError):
    """A v2 ingest checkpoint or write failed closed."""

    def __init__(self, message: str, *, failure_class: str = "ingest_v2") -> None:
        super().__init__(message)
        self.failure_class = failure_class


class IngestPaused(NexusError):
    """Deterministic stop. The open segment stays incomplete. Not a live signal."""


def is_retryable_failure(failure_class: str) -> bool:
    """Retry only transient classes. Does not change extraction classification."""
    if failure_class in _NON_RETRYABLE:
        return False
    return failure_class in _RETRYABLE


def _is_transient_transport(exc: BaseException) -> bool:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        name = type(current).__name__.lower()
        if isinstance(current, (ConnectionError, TimeoutError)):
            return True
        if any(token in name for token in ("connection", "transport", "temporar", "reset")):
            return True
        current = current.__cause__ or current.__context__
    return False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _digest_id(prefix: str, material: str) -> str:
    return f"{prefix}_{sha256(material.encode('utf-8')).hexdigest()[:32]}"


def checkpoint_dir(data_path: Path) -> Path:
    return data_path / "ingest" / "v2" / "checkpoints"


def ledger_path(data_path: Path) -> Path:
    return data_path / "ingest" / "v2" / "memories.json"


def ingest_log_path(data_path: Path) -> Path:
    return data_path / "ingest" / "v2" / "ingest_log.jsonl"


def pause_flag_path(data_path: Path) -> Path:
    return data_path / "ingest" / "v2" / "PAUSED"


def review_queue_path(data_path: Path) -> Path:
    return data_path / "ingest" / "v2" / "review_queue.jsonl"


def canary_dir(data_path: Path) -> Path:
    return data_path / "ingest" / "v2" / "canary"


def canary_log_path(data_path: Path) -> Path:
    return canary_dir(data_path) / "writes.jsonl"


def canary_snapshot_path(data_path: Path, day: str) -> Path:
    return canary_dir(data_path) / "snapshots" / f"{day}.json"


def is_paused(data_path: Path) -> bool:
    flag = pause_flag_path(data_path)
    return flag.is_file() and not flag.is_symlink()


def set_paused(data_path: Path, paused: bool = True) -> None:
    path = pause_flag_path(data_path)
    if not paused:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        return
    _prepare_dir(path.parent)
    path.write_text("paused\n", encoding="utf-8")
    path.chmod(0o600)


def pause_ingest(config: NexusConfig) -> dict[str, Any]:
    """Stop live vault writes. Shadow JSONL continues."""
    set_paused(config.data_path, True)
    return {
        "ok": True,
        "paused": True,
        "writes_performed": False,
        "vault_writes": False,
        "mode": "shadow-log",
        "message": "live writes paused; shadow log remains",
    }


def unpause_ingest(config: NexusConfig) -> dict[str, Any]:
    """Clear the pause flag. Does not extract or write."""
    set_paused(config.data_path, False)
    return {
        "ok": True,
        "paused": False,
        "writes_performed": False,
        "vault_writes": False,
        "extraction_called": False,
        "mode": "writes-armed",
        "message": "pause flag cleared; live writes follow the next explicit run",
    }


def canary_writes_today(data_path: Path) -> int:
    path = canary_log_path(data_path)
    if not path.is_file() or path.is_symlink():
        return 0
    today = _utc_now()[:10]
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(row.get("at") or "")[:10] == today:
            count += 1
    return count


def record_canary_write(data_path: Path, ingest_id: str) -> None:
    path = canary_log_path(data_path)
    _prepare_dir(path.parent)
    line = json.dumps(
        {"at": _utc_now(), "ingest_id": ingest_id, "writes": "canary"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded = (line + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.path.islink(path):
            raise IngestV2Error("refusing to append through a symlink")
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def snapshot_canonical(config: NexusConfig) -> dict[str, Any]:
    """Hash Nexus/ files and the derived index. Does not copy Vault contents."""
    if config.vault_path is None:
        raise IngestV2Error("vault_path is required for canary snapshot")
    files: list[dict[str, Any]] = []
    root = config.vault_path / "Nexus"
    if root.is_dir() and not root.is_symlink():
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(config.vault_path).as_posix()
            if not relative.startswith("Nexus/"):
                continue
            files.append(
                {
                    "path": relative,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
    index_sha = None
    if config.index_path.is_file() and not config.index_path.is_symlink():
        index_sha = sha256(config.index_path.read_bytes()).hexdigest()
    day = _utc_now()[:10]
    payload = {
        "captured_at": _utc_now(),
        "file_count": len(files),
        "index_sha256": index_sha,
        "files": files,
    }
    target = canary_snapshot_path(config.data_path, day)
    if not target.exists():
        atomic_json(target, payload)
    return payload


def prepare_canary_write(config: NexusConfig, *, confirm: str | None) -> dict[str, Any]:
    """Arm one labeled canary write. Does not extract. Max 25 ingest/day."""
    if confirm != CANARY_CONFIRM:
        raise IngestV2Error("canary-write requires --confirm canary")
    if not config.ingest_pipeline_v2:
        raise IngestV2Error("ingest_pipeline_v2 is off")
    if config.auto_publish_enabled:
        raise IngestV2Error("auto_publish_enabled must stay false")
    if config.vault_path is None:
        raise IngestV2Error("vault_path is required for canary write")
    if is_paused(config.data_path):
        raise IngestV2Error("ingest is paused")
    used = canary_writes_today(config.data_path)
    if used >= CANARY_DAILY_LIMIT:
        raise IngestV2Error("canary daily limit reached")
    snapshot = snapshot_canonical(config)
    return {
        "ok": True,
        "used_today": used,
        "limit": CANARY_DAILY_LIMIT,
        "snapshot_files": snapshot["file_count"],
        "extraction_called": False,
        "auto_publish_enabled": False,
    }


def _canonical_paths(
    config: NexusConfig, records: list[dict[str, Any]]
) -> list[str]:
    if config.vault_path is None:
        return []
    repository = VaultRepository(config.vault_path)
    paths: list[str] = []
    for record in records:
        try:
            memory = _memory_record(record)
        except (NexusError, KeyError, TypeError, ValueError):
            continue
        relative = repository.record_path(memory)
        path = config.vault_path / relative
        if path.is_file() and not path.is_symlink():
            paths.append(relative.as_posix())
    return paths


def _tombstone_canonical(
    config: NexusConfig, records: list[dict[str, Any]], *, ingest_id: str
) -> dict[str, Any]:
    """Rewrite matching Vault files as retracted, then rebuild the derived index."""
    result: dict[str, Any] = {"wrote": False, "file_count": 0, "paths": []}
    if config.vault_path is None:
        return result
    repository = VaultRepository(config.vault_path)
    retracted: list[Memory] = []
    expected: dict[str, str] = {}
    for record in records:
        row = dict(record)
        row["status"] = "retracted"
        try:
            memory = _memory_record(row)
        except (NexusError, KeyError, TypeError, ValueError):
            continue
        path = config.vault_path / repository.record_path(memory)
        if not path.is_file() or path.is_symlink():
            continue
        expected[memory.id] = repository.current_hash(memory)
        retracted.append(memory)
        result["paths"].append(repository.record_path(memory).as_posix())
    if not retracted:
        return result
    try:
        repository.commit_records(
            retracted,
            run_id=_digest_id("run", f"rollback:{ingest_id}"),
            expected_hashes=expected,
        )
        rebuild_index(config.vault_path, config.index_path)
    except (NexusError, OSError) as exc:
        raise IngestV2Error("canonical rollback failed", failure_class="vault_failed") from exc
    result["wrote"] = True
    result["file_count"] = len(retracted)
    return result


def rollback_batch(
    config: NexusConfig,
    ingest_id: str,
    *,
    apply: bool = False,
    confirm: str | None = None,
) -> dict[str, Any]:
    """Tombstone one ingest batch. Default is dry-run; apply needs exact confirm."""
    if not ingest_id.strip():
        raise IngestV2Error("ingest_id is required")
    if apply and confirm != ingest_id:
        raise IngestV2Error("rollback apply requires --confirm matching ingest_id")
    records = load_ledger(config.data_path)
    matched = [
        record
        for record in records
        if record.get("ingest_id") == ingest_id or record.get("batch_id") == ingest_id
    ]
    paths = _canonical_paths(config, matched)
    payload: dict[str, Any] = {
        "ok": True,
        "ingest_id": ingest_id,
        "dry_run": not apply,
        "record_count": len(matched),
        "record_ids": [str(record["id"]) for record in matched if record.get("id")],
        "active_count": sum(1 for record in matched if record.get("status") == "active"),
        "tombstoned": 0,
        "canonical_file_count": len(paths),
        "writes_performed": False,
        "vault_writes": False,
        "canonical_untouched": True,
        "extraction_called": False,
    }
    if not apply:
        return payload
    vaulted = _tombstone_canonical(config, matched, ingest_id=ingest_id)
    changed = 0
    for record in matched:
        if record.get("status") in {"active", "superseded"}:
            record["status"] = "retracted"
            record["tombstoned"] = True
            changed += 1
    if changed:
        _save_ledger(config.data_path, records)
    payload["tombstoned"] = changed
    payload["active_count"] = 0
    payload["dry_run"] = False
    payload["canonical_file_count"] = int(vaulted["file_count"])
    payload["vault_writes"] = bool(vaulted["wrote"])
    payload["canonical_untouched"] = not vaulted["wrote"]
    payload["writes_performed"] = changed > 0 or bool(vaulted["wrote"])
    return payload


def reprocess_failed(config: NexusConfig, ingest_id: str) -> dict[str, Any]:
    """Arm FAILED_SEGMENT rows for the next run. Does not call a model."""
    if not config.ingest_pipeline_v2:
        raise IngestV2Error("ingest_pipeline_v2 is off")
    if not ingest_id.strip():
        raise IngestV2Error("ingest_id is required")
    checkpoint = load_checkpoint(config.data_path, ingest_id)
    if checkpoint is None:
        raise IngestV2Error("checkpoint not found")
    segments = checkpoint.get("segments")
    if not isinstance(segments, dict):
        raise IngestV2Error("checkpoint is invalid")
    reset: list[str] = []
    for item in segments.values():
        if not isinstance(item, dict) or item.get("status") != FAILED_SEGMENT:
            continue
        item["status"] = "incomplete"
        item["attempt_count"] = 0
        item["failure_class"] = None
        item["completed_at"] = None
        extraction = item.get("extraction") if isinstance(item.get("extraction"), dict) else {}
        item["extraction"] = {
            "timeout_count": int(extraction.get("timeout_count") or 0),
            "reprocess": True,
        }
        if item.get("segment_id"):
            reset.append(str(item["segment_id"]))
    if reset:
        _save_checkpoint(config.data_path, checkpoint)
        append_observation(
            config.data_path,
            _observation(
                ingest_id=ingest_id,
                conversation_id=checkpoint.get("conversation_id"),
                status="RUNNING",
                writes="none",
                final_status="reprocess_armed",
                segment_count=len(reset),
            ),
        )
    return {
        "ok": True,
        "ingest_id": ingest_id,
        "reprocess_count": len(reset),
        "segment_ids": reset,
        "extraction_called": False,
        "writes_performed": False,
        "vault_writes": False,
    }


def review_queue_payload(config: NexusConfig) -> dict[str, Any]:
    """Read-only review/reprocess queue. No statements, no model call."""
    if not config.ingest_pipeline_v2:
        return {
            "ok": True,
            "ingest_pipeline_v2": False,
            "count": 0,
            "items": [],
            "extraction_called": False,
        }
    path = review_queue_path(config.data_path)
    items: list[dict[str, Any]] = []
    if path.is_file() and not path.is_symlink():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                items.append(
                    {
                        "ingest_id": row.get("ingest_id"),
                        "conversation_id": row.get("conversation_id"),
                        "segment_id": row.get("segment_id"),
                        "reason": row.get("reason"),
                        "failure_class": row.get("failure_class"),
                        "review_id": row.get("review_id"),
                    }
                )
    return {
        "ok": True,
        "ingest_pipeline_v2": True,
        "count": len(items),
        "items": items[-100:],
        "extraction_called": False,
        "writes_performed": False,
    }


REPAIR_CONFIRM = "repair"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower))


def acceptance_report(config: NexusConfig) -> dict[str, Any]:
    """PII-free A8 rollup from checkpoints, ingest log, ledger and Vault."""
    data_path = config.data_path
    ckpt_dir = data_path / "ingest" / "v2" / "checkpoints"
    conv_worst: dict[str, str] = {}
    segment_status: Counter[str] = Counter()
    fail_class: Counter[str] = Counter()
    if ckpt_dir.is_dir() and not ckpt_dir.is_symlink():
        for path in ckpt_dir.glob("*.json"):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            cid = str(payload.get("conversation_id") or path.stem)
            worst = "completed"
            for item in (payload.get("segments") or {}).values():
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status") or "unknown")
                segment_status[status] += 1
                if item.get("failure_class"):
                    fail_class[str(item.get("failure_class"))] += 1
                if status == FAILED_SEGMENT:
                    worst = FAILED_SEGMENT
                elif status == "incomplete" and worst == "completed":
                    worst = "incomplete"
            rank = {"completed": 0, "incomplete": 1, "review": 1, FAILED_SEGMENT: 2}
            previous = conv_worst.get(cid)
            if previous is None or rank.get(worst, 9) > rank.get(previous, 0):
                conv_worst[cid] = worst
    unique = len(conv_worst)
    completed = sum(1 for status in conv_worst.values() if status == "completed")
    completion_pct = round(100 * completed / unique, 1) if unique else None

    completed_durations: list[float] = []
    failed_durations: list[float] = []
    first_attempt_completed: list[float] = []
    leftover_durations: list[float] = []
    non_leftover: list[float] = []
    log_dup = 0
    log_path = ingest_log_path(data_path)
    if log_path.is_file() and not log_path.is_symlink():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            log_dup += int(row.get("duplicate_prevented_count") or row.get("duplicates_prevented") or 0)
            duration = row.get("segment_duration_ms")
            if not isinstance(duration, (int, float)) or duration < 0:
                continue
            seconds = float(duration) / 1000
            status = row.get("segment_status")
            attempts = int(row.get("attempt_count") or 0)
            timeouts = int(row.get("timeout_count") or 0)
            leftover = (
                status == FAILED_SEGMENT
                and attempts >= MAX_ATTEMPTS
                and timeouts >= MAX_ATTEMPTS
                and seconds >= 500
            )
            if leftover:
                leftover_durations.append(seconds)
            else:
                non_leftover.append(seconds)
            if status == "completed":
                completed_durations.append(seconds)
                if attempts == 1:
                    first_attempt_completed.append(seconds)
            elif status == FAILED_SEGMENT:
                failed_durations.append(seconds)
    all_durations = completed_durations + failed_durations
    p95_all = _percentile(all_durations, 95)
    p95_completed = _percentile(completed_durations, 95)
    p95_first = _percentile(first_attempt_completed, 95)
    p95_excluding_leftover = _percentile(non_leftover, 95)

    records = load_ledger(data_path) if ledger_path(data_path).is_file() else []
    fingerprints = [str(row.get("fingerprint")) for row in records if row.get("fingerprint")]
    statements = [
        sha256(str(row.get("statement") or "").strip().casefold().encode()).hexdigest()
        for row in records
        if isinstance(row.get("statement"), str) and str(row.get("statement")).strip()
    ]
    ledger_missing_prov = sum(
        1 for row in records if not (row.get("span_ids") or row.get("conversation_id"))
    )
    vault_ids: list[str] = []
    vault_missing_prov = 0
    memory_files = 0
    if config.vault_path is not None:
        memory_root = config.vault_path / "Nexus" / "Memory"
        if memory_root.is_dir() and not memory_root.is_symlink():
            for path in memory_root.rglob("*.md"):
                if path.is_symlink() or not path.is_file():
                    continue
                memory_files += 1
                try:
                    payload = extract_record_payload(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, VaultError):
                    vault_missing_prov += 1
                    continue
                record_id = payload.get("id")
                if isinstance(record_id, str) and record_id:
                    vault_ids.append(record_id)
                refs = payload.get("source_refs") or []
                if not refs:
                    vault_missing_prov += 1
                    continue
                if any(
                    not isinstance(ref, dict)
                    or not ref.get("conversation_id")
                    or not ref.get("span_ids")
                    or not ref.get("span_sha256")
                    for ref in refs
                ):
                    vault_missing_prov += 1
    vault_id_set = set(vault_ids)
    missing_rows = [
        row for row in records if row.get("id") and str(row["id"]) not in vault_id_set
    ]
    ledger_not_in_vault = len({str(row["id"]) for row in missing_rows})
    shadow_unpublished = sum(row.get("publication_intent") == "shadow" for row in missing_rows)
    canonical_missing = sum(row.get("publication_intent") == "canonical" for row in missing_rows)
    legacy_unclassified = len(missing_rows) - shadow_unpublished - canonical_missing
    payload = {
        "ok": True,
        "extraction_called": False,
        "auto_publish_enabled": bool(config.auto_publish_enabled),
        "timeout_cap_seconds": V2_HARD_TIMEOUT_SECONDS,
        "unique_conversations": unique,
        "completed_conversations": completed,
        "completion_pct": completion_pct,
        "segment_status": dict(segment_status),
        "failed_segment_class": dict(fail_class),
        "p95_segment_seconds": None if p95_all is None else round(p95_all, 3),
        "p95_completed_segment_seconds": None if p95_completed is None else round(p95_completed, 3),
        "p95_first_attempt_completed_seconds": None if p95_first is None else round(p95_first, 3),
        "p95_excluding_leftover_seconds": None
        if p95_excluding_leftover is None
        else round(p95_excluding_leftover, 3),
        "leftover_timeout_class_count": len(leftover_durations),
        "segment_duration_samples": len(all_durations),
        "duplicate_prevented_log_sum": log_dup,
        "ledger_records": len(records),
        "ledger_duplicate_fingerprints": len(fingerprints) - len(set(fingerprints)),
        "ledger_duplicate_statements": len(statements) - len(set(statements)),
        "ledger_missing_provenance": ledger_missing_prov,
        "vault_memory_files": memory_files,
        "vault_duplicate_ids": len(vault_ids) - len(set(vault_ids)),
        "vault_missing_provenance": vault_missing_prov,
        "ledger_ids_not_in_vault": ledger_not_in_vault,
        "shadow_unpublished_rows": shadow_unpublished,
        "canonical_missing_rows": canonical_missing,
        "legacy_unclassified_missing_rows": legacy_unclassified,
        "thresholds": {
            "completion_ge_95": bool(completion_pct is not None and completion_pct >= 95),
            "p95_lt_60": bool(p95_all is not None and p95_all < 60),
            "silent_loss_0": canonical_missing == 0 and legacy_unclassified == 0,
            "duplicate_0": (len(fingerprints) == len(set(fingerprints)))
            and (len(statements) == len(set(statements)))
            and (len(vault_ids) == len(set(vault_ids))),
            "canary_conversations_30": unique >= 30,
            "provenance_none_0": vault_missing_prov == 0 and ledger_missing_prov == 0,
        },
        "a8_all_required": False,
        "unmeasured": ["human_quality_30", "live_crash_resume"],
        "unmeasured_counted_as_pass": False,
        "vault_writes": False,
    }
    forbidden = {"conversation_id", "statement", "summary", "content", "heading"}
    if forbidden.intersection(payload):
        raise IngestV2Error("acceptance report leaked a forbidden key")
    return payload


def repair_missing_canonical(
    config: NexusConfig, *, confirm: str | None, apply: bool
) -> dict[str, Any]:
    """Write ledger rows that have no Vault file. Does not extract."""
    if not config.ingest_pipeline_v2:
        raise IngestV2Error("ingest_pipeline_v2 is off")
    if config.auto_publish_enabled:
        raise IngestV2Error("auto_publish_enabled must stay false")
    if apply and confirm != REPAIR_CONFIRM:
        raise IngestV2Error("repair apply requires --confirm repair")
    records = [
        row
        for row in load_ledger(config.data_path)
        if row.get("status") in {"active", "superseded"}
    ]
    missing = _missing_canonical_rows(config, records)
    payload: dict[str, Any] = {
        "ok": True,
        "missing_count": len(missing),
        "extraction_called": False,
        "auto_publish_enabled": False,
        "vault_writes": False,
        "written_file_count": 0,
        "written_prefixes": [],
    }
    if not apply or not missing:
        return payload
    _mark_canonical_intent(config.data_path, missing)
    written: list[str] = []
    _write_canonical(
        config,
        missing,
        run_material="repair-missing-canonical",
        index_writer=None,
        written_files=written,
    )
    prefixes = sorted({item.rsplit("/", 1)[0] if "/" in item else item for item in written})
    if any(not item.startswith("Nexus/") for item in written):
        raise IngestV2Error("namespace violation", failure_class="namespace")
    payload["vault_writes"] = True
    payload["written_file_count"] = len(written)
    payload["written_prefixes"] = prefixes
    return payload


def write_human_review_pack(config: NexusConfig, dest: Path) -> dict[str, Any]:
    """Copy canonical memories to a private scoresheet dir. Does not label quality."""
    if config.vault_path is None:
        raise IngestV2Error("vault_path is required")
    dest = dest.expanduser()
    if not dest.is_absolute():
        raise IngestV2Error("review pack destination must be absolute")
    if dest.is_symlink():
        raise IngestV2Error("review pack destination cannot be a symlink")
    data_root = config.data_path.resolve()
    dest_resolved = dest.resolve()
    if dest_resolved != data_root and data_root not in dest_resolved.parents:
        raise IngestV2Error("review pack must stay under data_path")
    _prepare_dir(dest)
    os.chmod(dest, 0o700)
    memory_root = config.vault_path / "Nexus" / "Memory"
    copied = 0
    rows: list[str] = [
        "index,nexus_id,memory_type,date,heading_chars,body_chars,provenance_ok,quality_faithful,quality_single_claim,quality_dated,notes"
    ]
    if memory_root.is_dir() and not memory_root.is_symlink():
        for index, path in enumerate(sorted(memory_root.rglob("*.md")), start=1):
            if path.is_symlink() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            payload = extract_record_payload(text)
            target = dest / f"{index:02d}_{path.stem}.md"
            target.write_text(text, encoding="utf-8")
            os.chmod(target, 0o600)
            heading = next((line[2:] for line in text.splitlines() if line.startswith("# ")), "")
            date = ""
            try:
                written = extract_written_at(text)
                date = written[:10]
            except VaultError:
                date = ""
            body = str(payload.get("summary") or "")
            refs = payload.get("source_refs") or []
            provenance_ok = "yes" if refs else "no"
            rows.append(
                ",".join(
                    [
                        str(index),
                        str(payload.get("id") or ""),
                        str(payload.get("type") or ""),
                        date,
                        str(len(heading)),
                        str(len(body)),
                        provenance_ok,
                        "",
                        "",
                        "",
                        "",
                    ]
                )
            )
            copied += 1
    sheet = dest / "scoresheet.csv"
    sheet.write_text("\n".join(rows) + "\n", encoding="utf-8")
    os.chmod(sheet, 0o600)
    guide = dest / "README.txt"
    guide.write_text(
        "Human A8 quality pack. Fill quality_* columns only. Do not commit this directory.\n"
        "quality_faithful: yes/no. quality_single_claim: yes/no. quality_dated: yes/no.\n"
        "NEXUS does not declare >=90% from this file until those columns are filled by Abidin.\n",
        encoding="utf-8",
    )
    os.chmod(guide, 0o600)
    return {
        "ok": True,
        "copied": copied,
        "sample_lt_30": copied < 30,
        "quality_declared": False,
        "extraction_called": False,
        "vault_writes": False,
        "dest_under_data_path": str(dest).startswith(str(config.data_path)),
    }


def _queue_review(data_path: Path, payload: dict[str, Any]) -> None:
    path = review_queue_path(data_path)
    if path.is_symlink():
        raise IngestV2Error("refusing to append through a symlink")
    _prepare_dir(path.parent)
    body = {
        "ingest_id": payload.get("ingest_id"),
        "conversation_id": payload.get("conversation_id"),
        "segment_id": payload.get("segment_id"),
        "reason": payload.get("reason"),
        "failure_class": payload.get("failure_class"),
        "review_id": payload.get("review_id"),
    }
    line = redact_secrets(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    encoded = (line + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def make_ingest_id(conversation: NormalizedConversation, schema_version: str) -> str:
    material = "|".join((conversation.external_conversation_id, schema_version))
    return sha256(material.encode("utf-8")).hexdigest()[:32]


def _prepare_dir(path: Path) -> None:
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise IngestV2Error("ingest directory must be a real directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise IngestV2Error("ingest directory must be a real directory")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a complete JSON document or leave the previous file untouched."""
    if path.is_symlink():
        raise IngestV2Error("refusing to write through a symlink")
    parent = path.parent
    _prepare_dir(parent)
    if parent.is_symlink():
        raise IngestV2Error("refusing to write through a symlink")
    encoded = redact_secrets(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".ingest-", dir=parent)
    temporary = Path(temporary_name)
    closed = False
    try:
        os.write(descriptor, encoded)
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        os.close(descriptor)
        closed = True
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if not closed:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def load_json(path: Path, *, kind: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise IngestV2Error(f"incomplete or unsafe {kind}")
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IngestV2Error(f"incomplete or invalid {kind}") from exc
    if not isinstance(payload, dict) or payload.get("complete") is not True:
        raise IngestV2Error(f"incomplete {kind} is invalid")
    return payload


def _checkpoint_path(data_path: Path, ingest_id: str) -> Path:
    return checkpoint_dir(data_path) / f"{ingest_id}.json"


def load_checkpoint(data_path: Path, ingest_id: str) -> dict[str, Any] | None:
    path = _checkpoint_path(data_path, ingest_id)
    if not path.exists():
        return None
    payload = load_json(path, kind="checkpoint")
    if payload.get("ingest_id") != ingest_id:
        raise IngestV2Error("checkpoint ingest_id does not match its path")
    return payload


def _blank_checkpoint(ingest_id: str, conversation_id: str, schema_version: str) -> dict[str, Any]:
    return {
        "complete": True,
        "ingest_id": ingest_id,
        "conversation_id": conversation_id,
        "schema_version": schema_version,
        "segments": {},
        "carry_forward": "",
    }


def _save_checkpoint(data_path: Path, payload: dict[str, Any]) -> None:
    payload["complete"] = True
    atomic_json(_checkpoint_path(data_path, str(payload["ingest_id"])), payload)


def _carry_text(statement: str) -> str:
    return redact_secrets(statement).strip()[:CARRY_FORWARD_CHARS]


def _restore_carry(carry_cell: list[str], state: dict[str, Any] | None) -> None:
    if not isinstance(state, dict):
        return
    extraction = state.get("extraction")
    text = None
    if isinstance(extraction, dict):
        text = extraction.get("carry_forward")
    if not isinstance(text, str) or not text.strip():
        text = state.get("carry_forward")
    if isinstance(text, str) and text.strip():
        carry_cell[0] = text.strip()[:CARRY_FORWARD_CHARS]


def load_ledger(data_path: Path) -> list[dict[str, Any]]:
    path = ledger_path(data_path)
    if not path.exists():
        return []
    payload = load_json(path, kind="memory ledger")
    records = payload.get("memories")
    if not isinstance(records, list):
        raise IngestV2Error("memory ledger is invalid")
    return [item for item in records if isinstance(item, dict)]


def _save_ledger(data_path: Path, records: list[dict[str, Any]]) -> None:
    atomic_json(ledger_path(data_path), {"complete": True, "memories": records})


def append_observation(data_path: Path, observation: dict[str, Any]) -> None:
    path = ingest_log_path(data_path)
    if path.is_symlink():
        raise IngestV2Error("refusing to append through a symlink")
    _prepare_dir(path.parent)
    body = {key: observation.get(key) for key in _OBSERVATION_KEYS}
    line = redact_secrets(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if contains_secret_value(line):
        line = redact_secrets(line)
    encoded = (line + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        if os.path.islink(path):
            raise IngestV2Error("refusing to append through a symlink")
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def current_memories(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer the current record. Historical superseded rows stay in the ledger."""
    return [record for record in records if record.get("status") == "active"]


def _candidate_fingerprint(candidate: ExtractionCandidate) -> str:
    return stable_hash(
        [
            candidate.kind.value,
            normalize_text(candidate.statement).casefold(),
            tuple(sorted(normalize_alias(item) for item in candidate.entity_mentions)),
            candidate.temporal_expression,
        ]
    )


def _memory_key(candidate: ExtractionCandidate) -> str:
    aliases = tuple(sorted(normalize_alias(item) for item in candidate.entity_mentions))
    return memory_fingerprint(
        kind=candidate.kind.value,
        statement=candidate.statement,
        entity_ids=aliases,
        effective_date=candidate.temporal_expression,
    )


@dataclass
class IngestRunReport:
    ingest_id: str
    conversation_id: str
    final_status: str
    segment_count: int
    accepted: int = 0
    rejected: int = 0
    duplicate_prevented_count: int = 0
    superseded_count: int = 0
    memories_created: int = 0
    extractor_calls: int = 0
    scrubbed_count: int = 0
    mirror_status: str = "not_requested"
    vault_written: bool = False
    error_class: str | None = None
    why: str | None = None
    written_files: list[str] = field(default_factory=list)
    segment_statuses: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.final_status != FAILED_SEGMENT,
            "ingest_pipeline_v2": True,
            "ingest_id": self.ingest_id,
            "conversation_id": self.conversation_id,
            "final_status": self.final_status,
            "segment_count": self.segment_count,
            "accepted_count": self.accepted,
            "rejected_count": self.rejected,
            "duplicate_prevented_count": self.duplicate_prevented_count,
            "duplicates_prevented": self.duplicate_prevented_count,
            "duplicates_created": 0,
            "scrubbed": self.scrubbed_count,
            "memories_created": self.memories_created,
            "superseded_count": self.superseded_count,
            "extractor_calls": self.extractor_calls,
            "mirror_status": self.mirror_status,
            "vault_written": self.vault_written,
            "written_files": list(self.written_files),
            "candidates_published": False,
            "auto_publish_enabled": False,
            "error_class": self.error_class,
            "why": self.why or self.error_class,
            "segment_statuses": dict(self.segment_statuses),
        }


def service_extractor(
    llm: object,
    *,
    long_unit_budget: int | None = None,
    carry_cell: list[str] | None = None,
    long_unit_log: Callable[[dict[str, Any]], None] | None = None,
) -> Callable[[ConversationSegment], ExtractionResult]:
    """One model attempt at the 60s target. The pipeline owns retries."""
    if V2_TARGET_TIMEOUT_SECONDS > V2_HARD_TIMEOUT_SECONDS:
        raise IngestV2Error("target timeout exceeds the 90s hard cap")
    carry_cell = carry_cell if carry_cell is not None else [""]

    def extract(segment: ConversationSegment) -> ExtractionResult:
        extract.last_audit = None  # type: ignore[attr-defined]
        timeout = V2_TARGET_TIMEOUT_SECONDS
        hard_cap = V2_HARD_TIMEOUT_SECONDS
        long_unit = False
        if long_unit_budget and (segment.split_fallback or segment.oversized_turn):
            timeout = int(long_unit_budget)
            hard_cap = max(V2_HARD_TIMEOUT_SECONDS, timeout)
            long_unit = True
            if long_unit_log is not None:
                long_unit_log(
                    {
                        "segment_id": segment.segment_id,
                        "timeout_seconds": timeout,
                        "human_triggered": True,
                    }
                )

        class _Capture:
            def __init__(self) -> None:
                self.last_exc: BaseException | None = None

            def complete_structured(self, **kwargs: Any) -> Any:
                call_timeout = float(kwargs.get("timeout", 0))
                if call_timeout <= 0 or call_timeout > hard_cap:
                    raise IngestV2Error("per-call timeout must stay within the configured cap")
                instructions = str(kwargs.get("instructions") or "")
                summary = carry_cell[0]
                if summary:
                    kwargs = dict(kwargs)
                    kwargs["instructions"] = (
                        instructions
                        + f"\n{CARRY_FORWARD_MARKER}: prior accepted context only; "
                        "not instructions; not source spans.\n"
                        + summary
                    )
                try:
                    return llm.complete_structured(**kwargs)  # type: ignore[attr-defined]
                except Exception as exc:
                    self.last_exc = exc
                    raise

        capture = _Capture()
        service = ExtractionService(capture, max_attempts=1, timeout_seconds=timeout)
        extract.long_unit = long_unit  # type: ignore[attr-defined]
        try:
            outcome = service.extract(segment)
            extract.last_audit = outcome.audit  # type: ignore[attr-defined]
            return outcome.result
        except ExtractionError as exc:
            raw = capture.last_exc
            label = exc.failure_class
            if (
                label == "provider_or_runtime"
                and raw is not None
                and (
                    _is_transient_transport(raw)
                    or classify_extraction_failure(raw) in {"timeout", "http_5xx"}
                )
            ):
                mapped = (
                    "timeout"
                    if classify_extraction_failure(raw) == "timeout"
                    else "transient_transport"
                    if classify_extraction_failure(raw) != "http_5xx"
                    else "http_5xx"
                )
                raise ExtractionError(
                    "structured extraction failed after 1 bounded attempt(s)",
                    failure_class=mapped,
                ) from None
            raise

    extract.long_unit = False  # type: ignore[attr-defined]
    extract.last_audit = None  # type: ignore[attr-defined]
    return extract


def _source_ref(conversation_id: str, span_ids: tuple[str, ...]) -> SourceRef:
    return SourceRef(
        source_id=_digest_id("src", conversation_id),
        conversation_id=conversation_id,
        span_ids=span_ids,
        span_sha256=stable_hash(list(span_ids)),
        excerpt="",
    )


def _enqueue_memory_review(
    data_path: Path,
    candidate: ExtractionCandidate,
    *,
    conversation_id: str,
    ingest_id: str,
    segment_id: str,
    memory_type: MemoryType,
) -> str:
    statement = redact_secrets(candidate.statement).strip()
    item = create_review_item(
        candidate_kind="memory",
        candidate={
            "statement": statement,
            "memory_type": memory_type.value,
            "confidence": candidate.confidence,
            "impact": Impact.LOW.value,
            "entity_ids": [],
            "extractor": {
                "name": "nexus-ingest-v2",
                "schema_version": EXTRACTION_SCHEMA_VERSION,
            },
        },
        reason_codes=("review_gate",),
        source_refs=(_source_ref(conversation_id, tuple(candidate.source_span_ids)),),
    )
    try:
        stored = ReviewStore(data_path).enqueue(item)
    except ReviewStoreError as exc:
        raise IngestV2Error("review enqueue failed", failure_class="review") from exc
    _queue_review(
        data_path,
        {
            "ingest_id": ingest_id,
            "conversation_id": conversation_id,
            "segment_id": segment_id,
            "reason": "review_gate",
            "failure_class": "review",
            "review_id": stored.id,
        },
    )
    return stored.id


def _match_prior(token: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    folded = normalize_text(token).casefold()
    for record in records:
        if record.get("id") == token or record.get("fingerprint") == token:
            return record
        statement = record.get("statement")
        if isinstance(statement, str) and normalize_text(statement).casefold() == folded:
            return record
    return None


def _claim_duplicate(statement: str, records: list[dict[str, Any]]) -> bool:
    folded = normalize_text(statement).casefold()
    if not folded:
        return False
    for record in records:
        if record.get("status") != "active":
            continue
        other = normalize_text(str(record.get("statement") or "")).casefold()
        if not other:
            continue
        if other == folded:
            return True
        if SequenceMatcher(None, folded, other).ratio() >= CLAIM_SIMILARITY_THRESHOLD:
            return True
    return False


def _collapse_supersede_chains(records: list[dict[str, Any]]) -> None:
    by_id = {str(record["id"]): record for record in records if record.get("id")}

    def tip_id(start: str) -> str:
        seen: set[str] = set()
        current = start
        while current in by_id and current not in seen:
            seen.add(current)
            nxt = by_id[current].get("superseded_by")
            if not nxt:
                return current
            current = str(nxt)
        return current

    for record in records:
        successor = record.get("superseded_by")
        if not successor:
            continue
        resolved = tip_id(str(successor))
        record["status"] = "superseded"
        record["superseded_by"] = resolved
    for record in records:
        if record.get("status") != "active":
            continue
        record["supersedes"] = [
            str(item["id"])
            for item in records
            if item.get("superseded_by") == record.get("id")
        ]


def _consider_candidate(
    candidate: ExtractionCandidate,
    *,
    conversation_id: str,
    ingest_id: str,
    memory_type: MemoryType | None,
    records: list[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """Risk gate, then scrub. Returns a disposition and an optional new row."""
    if candidate.kind.value != "memory":
        return "policy_reject", None
    if memory_type is None:
        return "policy_reject", None
    if contains_secret_value(candidate.statement):
        return "scrubber_reject", None
    statement = redact_secrets(candidate.statement).strip()
    if not statement or contains_secret_value(statement) or statement != candidate.statement.strip():
        return "scrubber_reject", None
    gate = ingest_write_disposition(
        statement,
        candidate.confidence,
        ambiguity_flags=candidate.ambiguity_flags,
    )
    if gate == "reject":
        return "rejected", None
    if gate == "review":
        return "review", None
    fingerprint = _memory_key(candidate)
    if any(record.get("fingerprint") == fingerprint for record in records):
        return "duplicate", None
    if _claim_duplicate(statement, records):
        return "duplicate", None
    supersedes: list[str] = []
    for token in candidate.possible_supersedes:
        prior = _match_prior(token, records)
        if prior is None or prior.get("id") in supersedes:
            continue
        if prior.get("fingerprint") == fingerprint:
            return "duplicate", None
        prior["status"] = "superseded"
        supersedes.append(str(prior["id"]))
    memory_id = _digest_id("mem", fingerprint)
    for prior_id in supersedes:
        for record in records:
            if record.get("id") == prior_id:
                record["superseded_by"] = memory_id
    row = {
        "id": memory_id,
        "fingerprint": fingerprint,
        "candidate_fingerprint": _candidate_fingerprint(candidate),
        "statement": statement,
        "status": "active",
        "memory_type": memory_type.value,
        "confidence": candidate.confidence,
        "conversation_id": conversation_id,
        "span_ids": list(candidate.source_span_ids),
        "supersedes": supersedes,
        "superseded_by": None,
        "ingest_id": ingest_id,
        "batch_id": ingest_id,
        "publication_intent": "shadow",
    }
    records.append(row)
    _collapse_supersede_chains(records)
    return "accepted", row


def _memory_record(row: dict[str, Any]) -> Memory:
    raw_status = str(row["status"])
    if raw_status == "retracted":
        status = RecordStatus.RETRACTED
    elif raw_status == "superseded":
        status = RecordStatus.SUPERSEDED
    else:
        status = RecordStatus.ACTIVE
    superseded_by = row.get("superseded_by")
    return Memory(
        id=str(row["id"]),
        type=MemoryType(str(row["memory_type"])),
        summary=str(row["statement"]),
        source_refs=(
            _source_ref(str(row["conversation_id"]), tuple(row["span_ids"])),
        ),
        confidence=float(row["confidence"]),
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        status=status,
        supersedes=tuple(row.get("supersedes") or ()),
        superseded_by=str(superseded_by) if superseded_by else None,
        extractor={"name": "nexus-ingest-v2", "schema_version": EXTRACTION_SCHEMA_VERSION},
    )


def _verify_canonical(
    config: NexusConfig,
    memories: list[Memory],
    repository: VaultRepository,
) -> list[dict[str, Any]]:
    written: list[dict[str, Any]] = []
    assert config.vault_path is not None
    for memory in memories:
        relative = repository.record_path(memory)
        posix = relative.as_posix()
        if not posix.startswith("Nexus/"):
            raise IngestV2Error("namespace violation", failure_class="namespace")
        path = config.vault_path / relative
        if path.name.endswith(".icloud") or Path(str(path) + ".icloud").exists():
            raise IngestV2Error("icloud stub", failure_class="degraded")
        if not path.is_file() or path.is_symlink():
            raise IngestV2Error("verify failed", failure_class="vault_failed")
        text = path.read_text(encoding="utf-8")
        written.append(
            {
                "path": posix,
                "sha256": repository.current_hash(memory),
                "line_count": text.count("\n"),
            }
        )
    return written


def _load_vault_memories(config: NexusConfig, repository: VaultRepository) -> list[Memory]:
    assert config.vault_path is not None
    root = config.vault_path / "Nexus" / "Memory"
    if not root.is_dir():
        return []
    loaded: list[Memory] = []
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink() or not path.is_file():
            raise IngestV2Error("canonical record is not a regular file", failure_class="vault_failed")
        try:
            loaded.append(memory_from_payload(extract_record_payload(path.read_text(encoding="utf-8"))))
        except (NexusError, OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
            raise IngestV2Error("canonical memory payload is invalid", failure_class="vault_failed") from exc
    return loaded


def _current_memory_view_write(
    config: NexusConfig,
    repository: VaultRepository,
    memories: list[Memory],
) -> object:
    assert config.vault_path is not None
    by_id = {item.id: item for item in _load_vault_memories(config, repository)}
    for memory in memories:
        by_id[memory.id] = memory
    view_path = config.vault_path / "Nexus" / "Views" / "Current-Memory.md"
    expected = None
    if view_path.exists():
        if view_path.is_symlink() or not view_path.is_file():
            raise IngestV2Error("current memory view is unsafe", failure_class="vault_failed")
        expected = sha256(view_path.read_bytes()).hexdigest()
    return current_memory_view_write(by_id.values(), repository, expected_sha256=expected)


def _write_canonical(
    config: NexusConfig,
    rows: list[dict[str, Any]],
    *,
    run_material: str,
    index_writer: Callable[[Path, Path], object] | None,
    written_files: list[str] | None = None,
) -> str:
    if config.vault_path is None:
        raise IngestV2Error("vault_path is required for a canonical write", failure_class="vault_failed")
    if config.auto_publish_enabled:
        raise IngestV2Error("auto_publish_enabled must stay false", failure_class="policy_reject")
    repository = VaultRepository(config.vault_path)
    memories = [_memory_record(row) for row in rows if row["status"] in {"active", "superseded"}]
    expected: dict[str, str] = {}
    for memory in memories:
        path = config.vault_path / repository.record_path(memory)
        if path.exists():
            expected[memory.id] = repository.current_hash(memory)
    try:
        repository.commit_records(
            memories,
            run_id=_digest_id("run", run_material),
            expected_hashes=expected,
            generated_writes=(_current_memory_view_write(config, repository, memories),),
        )
    except NexusError as exc:
        raise IngestV2Error("canonical write failed", failure_class="vault_failed") from exc
    verified = _verify_canonical(config, memories, repository)
    view_relative = Path("Nexus/Views/Current-Memory.md")
    view_path = config.vault_path / view_relative
    if view_path.name.endswith(".icloud") or Path(str(view_path) + ".icloud").exists():
        raise IngestV2Error("icloud stub", failure_class="degraded")
    if not view_path.is_file() or view_path.is_symlink():
        raise IngestV2Error("verify failed", failure_class="vault_failed")
    verified.append(
        {
            "path": view_relative.as_posix(),
            "sha256": sha256(view_path.read_bytes()).hexdigest(),
            "line_count": view_path.read_text(encoding="utf-8").count("\n"),
        }
    )
    if written_files is not None:
        written_files.extend(str(item["path"]) for item in verified)
    writer = index_writer or rebuild_index
    try:
        writer(config.vault_path, config.index_path)
    except NexusIndexError as exc:
        raise IngestV2Error("mirror rebuild pending retry", failure_class="mirror_retry") from exc
    return "obsidian+sqlite"


def _missing_canonical_rows(
    config: NexusConfig, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if config.vault_path is None:
        return list(rows)
    repository = VaultRepository(config.vault_path)
    missing: list[dict[str, Any]] = []
    for record in rows:
        try:
            memory = _memory_record(record)
        except (NexusError, KeyError, TypeError, ValueError):
            continue
        path = config.vault_path / repository.record_path(memory)
        if not path.is_file():
            missing.append(record)
    return missing


def _promotable_ledger_rows(
    records: list[dict[str, Any]],
    *,
    ingest_id: str,
    conversation_id: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if record.get("status") in {"active", "superseded"}
        and (
            record.get("ingest_id") == ingest_id
            or record.get("conversation_id") == conversation_id
        )
    ]


def _commit_canonical(
    config: NexusConfig,
    rows: list[dict[str, Any]],
    *,
    ingest_id: str,
    report: IngestRunReport,
    index_writer: Callable[[Path, Path], object] | None,
) -> str:
    if not rows:
        return "none"
    _mark_canonical_intent(config.data_path, rows)
    try:
        writes = _write_canonical(
            config,
            rows,
            run_material=ingest_id + ":" + ",".join(sorted(str(row["id"]) for row in rows)),
            index_writer=index_writer,
            written_files=report.written_files,
        )
        report.vault_written = True
        report.mirror_status = "current"
        return writes
    except IngestV2Error as exc:
        report.error_class = exc.failure_class
        report.why = exc.failure_class
        if exc.failure_class == "mirror_retry":
            report.vault_written = True
            report.mirror_status = "retry"
            report.final_status = "DEGRADED"
            return "obsidian_sqlite_retry"
        if exc.failure_class == "degraded":
            report.vault_written = True
            report.mirror_status = "retry"
            report.final_status = "DEGRADED"
            return "icloud_degraded"
        report.mirror_status = "not_written"
        report.final_status = FAILED_SEGMENT
        return "none"


def _mark_canonical_intent(data_path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist intent before a canonical attempt, including shadow promotions."""
    # Record publication intent before attempting the Vault write. A crash or
    # failed write must remain visible as a missing canonical record.
    requested_ids = {str(row["id"]) for row in rows}
    ledger = load_ledger(data_path)
    for row in ledger:
        if str(row.get("id")) in requested_ids:
            row["publication_intent"] = "canonical"
    _save_ledger(data_path, ledger)
    for row in rows:
        row["publication_intent"] = "canonical"


def _token_estimate(segment: ConversationSegment) -> int:
    return max(1, segment.character_count // 4)


def _logged_tokens(segment: ConversationSegment, extractor: object) -> int:
    audit = getattr(extractor, "last_audit", None)
    total = int(getattr(audit, "total_tokens", 0) or 0) if audit is not None else 0
    if total > 0:
        return total
    return _token_estimate(segment)


def _observation(**values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {key: None for key in _OBSERVATION_KEYS}
    base.update(values)
    if isinstance(base.get("error_class"), str):
        base["error_class"] = redact_secrets(str(base["error_class"]))[:80]
    return base


def _completed_end(segment_state: dict[str, Any]) -> int:
    """Highest frozen message index. Growing conversations pack only after this."""
    end = -1
    for item in segment_state.values():
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        value = item.get("end_message_index")
        if isinstance(value, int):
            end = max(end, value)
    return end


def _resume_after_index(segment_state: dict[str, Any]) -> int:
    """Do not pack past a FAILED_SEGMENT or incomplete hole."""
    unfinished_starts: list[int] = []
    for item in segment_state.values():
        if not isinstance(item, dict):
            continue
        start = item.get("start_message_index")
        status = item.get("status")
        if status in {FAILED_SEGMENT, "incomplete"} and isinstance(start, int):
            unfinished_starts.append(start)
        # Several fallback parts share one message index. A completed part
        # must never freeze the rest of that source message on resume.
        if status == "completed" and item.get("split_fallback") and isinstance(start, int):
            unfinished_starts.append(start)
    if unfinished_starts:
        return min(unfinished_starts) - 1
    return _completed_end(segment_state)


def _prune_stale_unfinished(
    segment_state: dict[str, Any], planned_ids: set[str]
) -> int:
    """Drop FAILED/incomplete rows whose segment_id is not in the new pack."""
    drop = [
        key
        for key, item in list(segment_state.items())
        if isinstance(item, dict)
        and item.get("status") in {FAILED_SEGMENT, "incomplete"}
        and str(item.get("segment_id") or key) not in planned_ids
    ]
    for key in drop:
        del segment_state[key]
    return len(drop)


def _completed_count(segment_state: dict[str, Any]) -> int:
    return sum(
        1
        for item in segment_state.values()
        if isinstance(item, dict) and item.get("status") == "completed"
    )


def _effective_pack_budget(
    checkpoint: dict[str, Any], target_chars: int, max_messages: int
) -> tuple[int, int]:
    chars = int(target_chars)
    msgs = int(max_messages)
    stored_chars = checkpoint.get("shrink_target_chars")
    stored_msgs = checkpoint.get("shrink_max_messages")
    if isinstance(stored_chars, int) and stored_chars >= 1:
        chars = min(chars, stored_chars)
    if isinstance(stored_msgs, int) and stored_msgs >= 1:
        msgs = min(msgs, stored_msgs)
    return chars, msgs


def _shrink_pack_budget(target_chars: int, max_messages: int) -> tuple[int, int]:
    chars = min(int(target_chars), MIN_SEGMENT_CHARS)
    return max(1, chars), 1


def _completed_split_fallback_at(segment_state: dict[str, Any], start: int) -> bool:
    for item in segment_state.values():
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        if item.get("split_fallback") and item.get("start_message_index") == start:
            return True
    return False


def _drop_unfinished_from(segment_state: dict[str, Any], start: int) -> None:
    for key, item in list(segment_state.items()):
        if not isinstance(item, dict) or item.get("status") == "completed":
            continue
        value = item.get("start_message_index")
        if isinstance(value, int) and value >= start:
            del segment_state[key]


def _timeout_shrink_tail(
    conversation: NormalizedConversation,
    segment: ConversationSegment,
    *,
    target_chars: int,
    max_messages: int,
    schema_version: str,
    start_ordinal: int,
    segment_state: dict[str, Any],
) -> tuple[ConversationSegment, ...]:
    """Rebuild remaining work at the smallest safe pack after a first timeout."""
    if _completed_split_fallback_at(segment_state, segment.start_message_index):
        return ()
    chars, msgs = _shrink_pack_budget(target_chars, max_messages)
    if (
        chars >= int(target_chars)
        and msgs >= int(max_messages)
        and segment.character_count <= chars
    ):
        return ()
    tail = segment_conversation_v2(
        conversation,
        target_chars=chars,
        max_messages=msgs,
        schema_version=schema_version,
        start_after_index=segment.start_message_index - 1,
        start_ordinal=start_ordinal,
    )
    if not tail:
        return ()
    first = tail[0]
    if (
        first.segment_id == segment.segment_id
        and first.content_hash == segment.content_hash
        and first.character_count == segment.character_count
    ):
        return ()
    return tail


def _incomplete_shrink_row(
    ingest_id: str,
    conversation: NormalizedConversation,
    segment: ConversationSegment,
    *,
    schema_version: str,
) -> dict[str, Any]:
    return {
        "ingest_id": ingest_id,
        "conversation_id": conversation.external_conversation_id,
        "segment_id": segment.segment_id,
        "start_message_index": segment.start_message_index,
        "end_message_index": segment.end_message_index,
        "schema_version": schema_version,
        "status": "incomplete",
        "attempt_count": 0,
        "started_at": None,
        "completed_at": None,
        "content_hash": segment.content_hash,
        "split_fallback": segment.split_fallback,
        "source_content_hash": (
            _range_content_hash(
                conversation, segment.start_message_index, segment.end_message_index
            )
            if segment.split_fallback
            else None
        ),
        "failure_class": None,
        "extraction": {"timeout_count": 0, "timeout_shrink": True},
    }


def _persist_shrink_tail(
    checkpoint: dict[str, Any],
    segment_state: dict[str, Any],
    *,
    ingest_id: str,
    conversation: NormalizedConversation,
    parent_start: int,
    tail: tuple[ConversationSegment, ...],
    chars: int,
    msgs: int,
    schema_version: str,
    carry: str,
) -> None:
    """Drop the timed-out parent and write child holes in one checkpoint save."""
    checkpoint["shrink_target_chars"] = chars
    checkpoint["shrink_max_messages"] = msgs
    checkpoint["carry_forward"] = carry
    _drop_unfinished_from(segment_state, parent_start)
    for child in tail:
        existing = segment_state.get(child.segment_id)
        if isinstance(existing, dict) and existing.get("status") == "completed":
            continue
        segment_state[child.segment_id] = _incomplete_shrink_row(
            ingest_id,
            conversation,
            child,
            schema_version=schema_version,
        )
    checkpoint["segments"] = segment_state


def _range_content_hash(
    conversation: NormalizedConversation, start: int, end: int
) -> str:
    texts = tuple(
        message.content_text
        for index, message in enumerate(conversation.messages)
        if start <= index <= end
        and message.include_for_extraction
        and message.content_text
    )
    return normalized_content_hash(texts)


def run_conversation(
    config: NexusConfig,
    conversation: NormalizedConversation,
    extractor: Callable[[ConversationSegment], ExtractionResult],
    *,
    write_canonical: bool = False,
    canonical_memory_type: MemoryType = MemoryType.PREFERENCE,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_segments: int | None = None,
    schema_version: str = SEGMENT_ID_SCHEMA_VERSION,
    index_writer: Callable[[Path, Path], object] | None = None,
    sleeper: Callable[[float], None] | None = None,
    carry_cell: list[str] | None = None,
) -> IngestRunReport:
    """Resume a conversation from the first incomplete segment."""
    if not config.ingest_pipeline_v2:
        raise IngestV2Error("ingest_pipeline_v2 is off")
    if config.auto_publish_enabled:
        raise IngestV2Error("auto_publish_enabled must stay false")
    if write_canonical and config.vault_path is None:
        raise IngestV2Error("vault_path is required for a canonical write")
    if is_paused(config.data_path):
        write_canonical = False
    carry_cell = carry_cell if carry_cell is not None else [""]

    ingest_id = make_ingest_id(conversation, schema_version)
    started = _utc_now()
    stored = load_checkpoint(config.data_path, ingest_id)
    checkpoint = stored or _blank_checkpoint(
        ingest_id, conversation.external_conversation_id, schema_version
    )
    segment_state: dict[str, Any] = checkpoint.setdefault("segments", {})
    pack_chars, pack_messages = _effective_pack_budget(
        checkpoint, target_chars, max_messages
    )
    resume_after = _resume_after_index(segment_state)
    segments = segment_conversation_v2(
        conversation,
        target_chars=pack_chars,
        max_messages=pack_messages,
        schema_version=schema_version,
        start_after_index=resume_after,
        start_ordinal=_completed_count(segment_state) + 1,
    )
    if _prune_stale_unfinished(segment_state, {item.segment_id for item in segments}):
        checkpoint["segments"] = segment_state
        _save_checkpoint(config.data_path, checkpoint)
    if not carry_cell[0]:
        prior = checkpoint.get("carry_forward")
        if isinstance(prior, str) and prior.strip():
            carry_cell[0] = prior.strip()[:CARRY_FORWARD_CHARS]
    records = load_ledger(config.data_path)
    dirty_ids: set[str] = set()
    report = IngestRunReport(
        ingest_id=ingest_id,
        conversation_id=conversation.external_conversation_id,
        final_status="completed",
        segment_count=len(segments),
    )
    for item in segment_state.values():
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        start = item.get("start_message_index")
        end = item.get("end_message_index")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        expected_hash = item.get(
            "source_content_hash" if item.get("split_fallback") else "content_hash"
        )
        if _range_content_hash(conversation, start, end) == expected_hash:
            continue
        _queue_review(
            config.data_path,
            {
                "ingest_id": ingest_id,
                "conversation_id": conversation.external_conversation_id,
                "segment_id": item.get("segment_id"),
                "reason": "content_hash_mismatch",
                "failure_class": "content_hash_mismatch",
            },
        )
        report.segment_statuses[str(item.get("segment_id"))] = "review"
        report.why = "content_hash_mismatch"
        report.final_status = "review"
    if report.why == "content_hash_mismatch":
        prevented = 0
        for item in segment_state.values():
            if not isinstance(item, dict) or item.get("status") != "completed":
                continue
            meta = item.get("extraction") or {}
            prevented += int(meta.get("accepted_count") or 0)
            prevented += int(meta.get("duplicate_prevented_count") or 0)
        report.duplicate_prevented_count = prevented
        report.segment_count = sum(
            1
            for item in segment_state.values()
            if isinstance(item, dict) and item.get("status") == "completed"
        )
        append_observation(
            config.data_path,
            _observation(
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
                started_at=started,
                finished_at=_utc_now(),
                schema_version=schema_version,
                status="COMPLETED",
                segment_count=report.segment_count,
                duplicate_prevented_count=prevented,
                duplicates_prevented=prevented,
                writes="none",
                final_status="review",
                error_class="content_hash_mismatch",
            ),
        )
        return report
    if not segments and any(
        isinstance(item, dict) and item.get("status") == "completed"
        for item in segment_state.values()
    ):
        prevented = 0
        for item in segment_state.values():
            if not isinstance(item, dict) or item.get("status") != "completed":
                continue
            meta = item.get("extraction") or {}
            prevented += int(meta.get("accepted_count") or 0)
            prevented += int(meta.get("duplicate_prevented_count") or 0)
        if report.why != "content_hash_mismatch":
            report.final_status = "already_processed"
        report.duplicate_prevented_count = prevented
        report.segment_count = sum(
            1
            for item in segment_state.values()
            if isinstance(item, dict) and item.get("status") == "completed"
        )
        if not report.segment_statuses:
            report.segment_statuses = {
                str(item.get("segment_id")): "completed"
                for item in segment_state.values()
                if isinstance(item, dict) and item.get("status") == "completed"
            }
        writes = "none"
        if write_canonical and report.final_status != "review":
            rows = _promotable_ledger_rows(
                records,
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
            )
            writes = _commit_canonical(
                config,
                _missing_canonical_rows(config, rows),
                ingest_id=ingest_id,
                report=report,
                index_writer=index_writer,
            )
        append_observation(
            config.data_path,
            _observation(
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
                started_at=started,
                finished_at=_utc_now(),
                schema_version=schema_version,
                status="COMPLETED",
                segment_count=report.segment_count,
                duplicate_prevented_count=prevented,
                duplicates_prevented=prevented,
                writes=writes,
                written_files=list(report.written_files),
                final_status=report.final_status,
            ),
        )
        return report
    all_completed = bool(segments) and all(
        isinstance(segment_state.get(segment.segment_id), dict)
        and segment_state[segment.segment_id].get("status") == "completed"
        and segment_state[segment.segment_id].get("content_hash") == segment.content_hash
        for segment in segments
    )
    if all_completed:
        prevented = 0
        for segment in segments:
            meta = segment_state[segment.segment_id].get("extraction") or {}
            prevented += int(meta.get("accepted_count") or 0)
            prevented += int(meta.get("duplicate_prevented_count") or 0)
        report.final_status = "already_processed"
        report.duplicate_prevented_count = prevented
        report.segment_statuses = {
            segment.segment_id: "completed" for segment in segments
        }
        writes = "none"
        if write_canonical:
            rows = _promotable_ledger_rows(
                records,
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
            )
            writes = _commit_canonical(
                config,
                _missing_canonical_rows(config, rows),
                ingest_id=ingest_id,
                report=report,
                index_writer=index_writer,
            )
        append_observation(
            config.data_path,
            _observation(
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
                started_at=started,
                finished_at=_utc_now(),
                schema_version=schema_version,
                status="COMPLETED",
                segment_count=len(segments),
                duplicate_prevented_count=prevented,
                duplicates_prevented=prevented,
                writes=writes,
                written_files=list(report.written_files),
                final_status="already_processed",
            ),
        )
        return report

    work: deque[ConversationSegment] = deque(segments)
    while work:
        segment = work.popleft()
        if is_paused(config.data_path):
            write_canonical = False
        state = segment_state.get(segment.segment_id)
        if isinstance(state, dict) and state.get("status") == "completed":
            if state.get("content_hash") != segment.content_hash:
                _queue_review(
                    config.data_path,
                    {
                        "ingest_id": ingest_id,
                        "conversation_id": conversation.external_conversation_id,
                        "segment_id": segment.segment_id,
                        "reason": "content_hash_mismatch",
                        "failure_class": "content_hash_mismatch",
                    },
                )
                report.segment_statuses[segment.segment_id] = "review"
                report.why = "content_hash_mismatch"
                continue
            _restore_carry(carry_cell, state)
            checkpoint["carry_forward"] = carry_cell[0]
            report.segment_statuses[segment.segment_id] = "completed"
            continue
        if isinstance(state, dict) and state.get("status") == FAILED_SEGMENT:
            if int(state.get("attempt_count") or 0) >= MAX_ATTEMPTS or not is_retryable_failure(
                str(state.get("failure_class") or "")
            ):
                report.segment_statuses[segment.segment_id] = FAILED_SEGMENT
                report.final_status = FAILED_SEGMENT
                report.error_class = state.get("failure_class")
                continue
        attempts = int(state.get("attempt_count") or 0) if isinstance(state, dict) else 0
        timeouts = int((state or {}).get("extraction", {}).get("timeout_count") or 0) if isinstance(state, dict) else 0
        segment_started = time.monotonic()
        started_at = (
            state.get("started_at") if isinstance(state, dict) and state.get("started_at") else _utc_now()
        )
        outcome: ExtractionResult | None = None
        failure_class: str | None = None
        last_attempt_ms = 0
        shrunk = False
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            attempt_started = time.monotonic()
            segment_state[segment.segment_id] = {
                "ingest_id": ingest_id,
                "conversation_id": conversation.external_conversation_id,
                "segment_id": segment.segment_id,
                "start_message_index": segment.start_message_index,
                "end_message_index": segment.end_message_index,
                "schema_version": schema_version,
                "status": "incomplete",
                "attempt_count": attempts,
                "started_at": started_at,
                "completed_at": None,
                "content_hash": segment.content_hash,
                "split_fallback": segment.split_fallback,
                "source_content_hash": (
                    _range_content_hash(
                        conversation, segment.start_message_index, segment.end_message_index
                    )
                    if segment.split_fallback else None
                ),
                "failure_class": None,
                "extraction": {"timeout_count": timeouts},
            }
            checkpoint["carry_forward"] = carry_cell[0]
            _save_checkpoint(config.data_path, checkpoint)
            try:
                outcome = extractor(segment)
                report.extractor_calls += 1
                last_attempt_ms = int((time.monotonic() - attempt_started) * 1000)
                failure_class = None
                break
            except IngestPaused:
                report.extractor_calls += 1
                last_attempt_ms = int((time.monotonic() - attempt_started) * 1000)
                report.final_status = "paused"
                report.segment_statuses[segment.segment_id] = "incomplete"
                checkpoint["carry_forward"] = carry_cell[0]
                _save_checkpoint(config.data_path, checkpoint)
                append_observation(
                    config.data_path,
                    _observation(
                        ingest_id=ingest_id,
                        conversation_id=conversation.external_conversation_id,
                        started_at=started,
                        finished_at=_utc_now(),
                        schema_version=schema_version,
                        segment_count=len(segments),
                        segment_id=segment.segment_id,
                        segment_range=[segment.start_message_index, segment.end_message_index],
                        segment_duration_ms=last_attempt_ms,
                        segment_wall_ms=int((time.monotonic() - segment_started) * 1000),
                        attempt_count=attempts,
                        retry_count=max(0, attempts - 1),
                        timeout_count=timeouts,
                        writes="none",
                        final_status="paused",
                    ),
                )
                return report
            except ExtractorBusy:
                last_attempt_ms = int((time.monotonic() - attempt_started) * 1000)
                attempts = max(0, attempts - 1)
                segment_state[segment.segment_id] = {
                    "ingest_id": ingest_id,
                    "conversation_id": conversation.external_conversation_id,
                    "segment_id": segment.segment_id,
                    "start_message_index": segment.start_message_index,
                    "end_message_index": segment.end_message_index,
                    "schema_version": schema_version,
                    "status": "incomplete",
                    "attempt_count": attempts,
                    "started_at": started_at if attempts else None,
                    "completed_at": None,
                    "content_hash": segment.content_hash,
                    "split_fallback": segment.split_fallback,
                    "source_content_hash": (
                        _range_content_hash(
                            conversation, segment.start_message_index, segment.end_message_index
                        )
                        if segment.split_fallback
                        else None
                    ),
                    "failure_class": None,
                    "extraction": {"timeout_count": timeouts},
                }
                report.final_status = "paused"
                report.segment_statuses[segment.segment_id] = "incomplete"
                checkpoint["carry_forward"] = carry_cell[0]
                checkpoint["segments"] = segment_state
                _save_checkpoint(config.data_path, checkpoint)
                append_observation(
                    config.data_path,
                    _observation(
                        ingest_id=ingest_id,
                        conversation_id=conversation.external_conversation_id,
                        started_at=started,
                        finished_at=_utc_now(),
                        schema_version=schema_version,
                        segment_count=len(segments),
                        segment_id=segment.segment_id,
                        segment_range=[segment.start_message_index, segment.end_message_index],
                        segment_duration_ms=last_attempt_ms,
                        segment_wall_ms=int((time.monotonic() - segment_started) * 1000),
                        attempt_count=attempts,
                        retry_count=0,
                        timeout_count=timeouts,
                        writes="none",
                        final_status="paused",
                    ),
                )
                return report
            except ExtractionError as exc:
                report.extractor_calls += 1
                last_attempt_ms = int((time.monotonic() - attempt_started) * 1000)
                failure_class = exc.failure_class
                if failure_class == "timeout":
                    timeouts += 1
                segment_state[segment.segment_id]["failure_class"] = failure_class
                segment_state[segment.segment_id]["extraction"] = {"timeout_count": timeouts}
                checkpoint["carry_forward"] = carry_cell[0]
                _save_checkpoint(config.data_path, checkpoint)
                if failure_class == "timeout" and attempts == 1:
                    tail = _timeout_shrink_tail(
                        conversation,
                        segment,
                        target_chars=pack_chars,
                        max_messages=pack_messages,
                        schema_version=schema_version,
                        start_ordinal=_completed_count(segment_state) + 1,
                        segment_state=segment_state,
                    )
                    if tail:
                        if max_segments is not None and len(tail) > max_segments:
                            segment_state[segment.segment_id]["status"] = FAILED_SEGMENT
                            checkpoint["carry_forward"] = carry_cell[0]
                            _save_checkpoint(config.data_path, checkpoint)
                            work.clear()
                            outcome = None
                            break
                        chars, msgs = _shrink_pack_budget(pack_chars, pack_messages)
                        pack_chars, pack_messages = chars, msgs
                        _persist_shrink_tail(
                            checkpoint,
                            segment_state,
                            ingest_id=ingest_id,
                            conversation=conversation,
                            parent_start=segment.start_message_index,
                            tail=tail,
                            chars=chars,
                            msgs=msgs,
                            schema_version=schema_version,
                            carry=carry_cell[0],
                        )
                        _save_checkpoint(config.data_path, checkpoint)
                        work.clear()
                        work.extend(tail)
                        shrunk = True
                        outcome = None
                        break
                    segment_state[segment.segment_id]["status"] = FAILED_SEGMENT
                    checkpoint["carry_forward"] = carry_cell[0]
                    _save_checkpoint(config.data_path, checkpoint)
                    outcome = None
                    break
                if not is_retryable_failure(failure_class) or attempts >= MAX_ATTEMPTS:
                    segment_state[segment.segment_id]["status"] = FAILED_SEGMENT
                    checkpoint["carry_forward"] = carry_cell[0]
                    _save_checkpoint(config.data_path, checkpoint)
                    outcome = None
                    break
                if sleeper is not None:
                    delay = RETRY_BACKOFF_SECONDS[
                        min(attempts - 1, len(RETRY_BACKOFF_SECONDS) - 1)
                    ]
                    sleeper(delay)
        duration_ms = last_attempt_ms
        wall_ms = int((time.monotonic() - segment_started) * 1000)
        if shrunk:
            report.segment_statuses[segment.segment_id] = "timeout_shrink"
            append_observation(
                config.data_path,
                _observation(
                    ingest_id=ingest_id,
                    conversation_id=conversation.external_conversation_id,
                    started_at=started,
                    finished_at=_utc_now(),
                    schema_version=schema_version,
                    status="RUNNING",
                    segment_count=len(segments),
                    segment_id=segment.segment_id,
                    segment_range=[segment.start_message_index, segment.end_message_index],
                    latency_ms=duration_ms,
                    token_estimate=_logged_tokens(segment, extractor),
                    retries=0,
                    segment_status="timeout_shrink",
                    segment_duration_ms=duration_ms,
                    segment_wall_ms=wall_ms,
                    attempt_count=attempts,
                    retry_count=0,
                    timeout_count=timeouts,
                    error_class="timeout",
                    writes="none",
                    final_status="timeout_shrink",
                ),
            )
            if is_paused(config.data_path):
                report.final_status = "paused"
                return report
            continue
        if outcome is None:
            report.segment_statuses[segment.segment_id] = FAILED_SEGMENT
            report.final_status = FAILED_SEGMENT
            report.error_class = failure_class
            report.why = failure_class
            _queue_review(
                config.data_path,
                {
                    "ingest_id": ingest_id,
                    "conversation_id": conversation.external_conversation_id,
                    "segment_id": segment.segment_id,
                    "reason": "FAILED_SEGMENT",
                    "failure_class": failure_class,
                },
            )
            append_observation(
                config.data_path,
                _observation(
                    ingest_id=ingest_id,
                    conversation_id=conversation.external_conversation_id,
                    started_at=started,
                    finished_at=_utc_now(),
                    schema_version=schema_version,
                    status="FAILED",
                    segment_count=len(segments),
                    segment_id=segment.segment_id,
                    segment_range=[segment.start_message_index, segment.end_message_index],
                    latency_ms=duration_ms,
                    token_estimate=_logged_tokens(segment, extractor),
                    retries=max(0, attempts - 1),
                    segment_status=FAILED_SEGMENT,
                    segment_duration_ms=duration_ms,
                    segment_wall_ms=wall_ms,
                    attempt_count=attempts,
                    retry_count=max(0, attempts - 1),
                    timeout_count=timeouts,
                    error_class=failure_class,
                    errors=[{"segment_id": segment.segment_id, "failure_class": failure_class}],
                    writes="none",
                    final_status=FAILED_SEGMENT,
                ),
            )
            continue

        accepted = rejected = duplicates = superseded = 0
        fingerprints: list[str] = []
        before = {
            record["id"]: (record.get("status"), record.get("superseded_by")) for record in records
        }
        known_ids = set(before)
        for candidate in outcome.candidates:
            fingerprints.append(_candidate_fingerprint(candidate))
            disposition, row = _consider_candidate(
                candidate,
                conversation_id=conversation.external_conversation_id,
                ingest_id=ingest_id,
                memory_type=canonical_memory_type,
                records=records,
            )
            if disposition == "accepted" and row is not None:
                accepted += 1
                report.memories_created += 1
                dirty_ids.add(str(row["id"]))
                carry_cell[0] = _carry_text(str(row["statement"]))
            elif disposition == "duplicate":
                duplicates += 1
                report.duplicate_prevented_count += 1
            elif disposition == "review":
                rejected += 1
                report.rejected += 1
                if canonical_memory_type is None:
                    raise IngestV2Error("review enqueue failed", failure_class="review")
                _enqueue_memory_review(
                    config.data_path,
                    candidate,
                    conversation_id=conversation.external_conversation_id,
                    ingest_id=ingest_id,
                    segment_id=segment.segment_id,
                    memory_type=canonical_memory_type,
                )
            elif disposition == "scrubber_reject":
                rejected += 1
                report.rejected += 1
                report.scrubbed_count += 1
            else:
                rejected += 1
                report.rejected += 1
        for record in records:
            previous = before.get(record["id"])
            if record["id"] not in known_ids or previous != (
                record.get("status"),
                record.get("superseded_by"),
            ):
                dirty_ids.add(str(record["id"]))
        superseded = sum(
            1
            for record in records
            if before.get(record["id"], (None, None))[0] == "active"
            and record.get("status") == "superseded"
        )
        report.superseded_count += superseded
        report.accepted += accepted
        segment_state[segment.segment_id] = {
            "ingest_id": ingest_id,
            "conversation_id": conversation.external_conversation_id,
            "segment_id": segment.segment_id,
            "start_message_index": segment.start_message_index,
            "end_message_index": segment.end_message_index,
            "schema_version": schema_version,
            "status": "completed",
            "attempt_count": attempts,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "content_hash": segment.content_hash,
            "split_fallback": segment.split_fallback,
            "source_content_hash": (
                _range_content_hash(
                    conversation, segment.start_message_index, segment.end_message_index
                )
                if segment.split_fallback else None
            ),
            "failure_class": None,
            "extraction": {
                "candidate_count": len(outcome.candidates),
                "accepted_count": accepted,
                "rejected_count": rejected,
                "duplicate_prevented_count": duplicates,
                "candidate_fingerprints": fingerprints,
                "timeout_count": timeouts,
                "carry_forward": carry_cell[0],
            },
        }
        checkpoint["carry_forward"] = carry_cell[0]
        _save_checkpoint(config.data_path, checkpoint)
        _save_ledger(config.data_path, records)
        report.segment_statuses[segment.segment_id] = "completed"
        append_observation(
            config.data_path,
            _observation(
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
                started_at=started,
                finished_at=_utc_now(),
                schema_version=schema_version,
                status="RUNNING",
                segment_count=len(segments),
                segment_id=segment.segment_id,
                segment_range=[segment.start_message_index, segment.end_message_index],
                latency_ms=duration_ms,
                token_estimate=_logged_tokens(segment, extractor),
                retries=max(0, attempts - 1),
                segment_status="completed",
                segment_duration_ms=duration_ms,
                segment_wall_ms=wall_ms,
                attempt_count=attempts,
                retry_count=max(0, attempts - 1),
                timeout_count=timeouts,
                candidate_count=len(outcome.candidates),
                accepted_count=accepted,
                rejected_count=rejected,
                duplicate_prevented_count=duplicates,
                duplicates_prevented=duplicates,
                scrubbed=report.scrubbed_count,
                superseded_count=superseded,
                writes="none",
                final_status="completed",
            ),
        )

    writes = "none"
    if write_canonical and report.final_status == "completed" and dirty_ids:
        changed = [record for record in records if record["id"] in dirty_ids]
        writes = _commit_canonical(
            config,
            _missing_canonical_rows(config, changed),
            ingest_id=ingest_id,
            report=report,
            index_writer=index_writer,
        )
        append_observation(
            config.data_path,
            _observation(
                ingest_id=ingest_id,
                conversation_id=conversation.external_conversation_id,
                started_at=started,
                finished_at=_utc_now(),
                schema_version=schema_version,
                status=(
                    "DEGRADED"
                    if report.final_status == "DEGRADED"
                    else "COMPLETED"
                    if report.final_status == "completed"
                    else "FAILED"
                ),
                segment_count=len(segments),
                writes=writes,
                written_files=list(report.written_files),
                error_class=report.error_class,
                final_status=report.final_status if report.mirror_status != "retry" else "completed",
                accepted_count=report.accepted,
                duplicate_prevented_count=report.duplicate_prevented_count,
                duplicates_prevented=report.duplicate_prevented_count,
                scrubbed=report.scrubbed_count,
                superseded_count=report.superseded_count,
            ),
        )
    return report


def run_inbox(
    config: NexusConfig,
    llm: object,
    *,
    relative_path: str,
    confirmed_sha256: str,
    conversation_id: str | None = None,
    max_segments: int = 20,
    max_segment_chars: int = DEFAULT_TARGET_CHARS,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    long_unit_budget: int | None = None,
    canary_write: bool = False,
    confirm: str | None = None,
) -> IngestRunReport:
    """Run one exact Inbox source through v2. Vault write only with canary confirm."""
    from .errors import SourceError
    from .ingest import _prepare_exact_source

    if not config.ingest_pipeline_v2:
        raise IngestV2Error("ingest_pipeline_v2 is off")
    if not MIN_SEGMENT_CHARS <= int(max_segment_chars) <= DEFAULT_TARGET_CHARS:
        raise IngestV2Error("max-segment-chars must stay within 500-12000")
    if not 1 <= int(max_messages) <= DEFAULT_MAX_MESSAGES:
        raise IngestV2Error("max-messages must stay within 1-12")
    prepared = _prepare_exact_source(
        config,
        relative_path=relative_path,
        confirmed_sha256=confirmed_sha256,
        conversation_id=conversation_id,
        max_segments=max_segments,
        max_segment_chars=max_segment_chars,
    )
    conversation = prepared.parsed.conversations[prepared.conversation_index]
    ingest_id = make_ingest_id(conversation, SEGMENT_ID_SCHEMA_VERSION)
    write_canonical = False
    if canary_write:
        prepare_canary_write(config, confirm=confirm)
        record_canary_write(config.data_path, ingest_id)
        write_canonical = True
    stored = load_checkpoint(config.data_path, ingest_id)
    stored_segments = stored.get("segments", {}) if isinstance(stored, dict) else {}
    pack_chars, pack_messages = _effective_pack_budget(
        stored or {}, max_segment_chars, max_messages
    )
    planned = segment_conversation_v2(
        conversation,
        target_chars=pack_chars,
        max_messages=pack_messages,
        start_after_index=_resume_after_index(stored_segments),
        start_ordinal=_completed_count(stored_segments) + 1,
    )
    if len(planned) > max_segments:
        raise SourceError("selected conversation exceeds max-segments before model execution")
    carry_cell = [""]
    uses: list[dict[str, Any]] = []

    def _log_long_unit(payload: dict[str, Any]) -> None:
        uses.append(payload)
        append_observation(
            config.data_path,
            _observation(
                ingest_id=None,
                conversation_id=conversation.external_conversation_id,
                long_unit=payload,
                status="RUNNING",
                writes="none",
            ),
        )

    report = run_conversation(
        config,
        conversation,
        service_extractor(
            llm,
            long_unit_budget=long_unit_budget,
            carry_cell=carry_cell,
            long_unit_log=_log_long_unit if long_unit_budget else None,
        ),
        write_canonical=write_canonical,
        canonical_memory_type=MemoryType.PREFERENCE,
        target_chars=max_segment_chars,
        max_messages=max_messages,
        max_segments=max_segments,
        sleeper=time.sleep,
        carry_cell=carry_cell,
    )
    if uses:
        payload = report.to_dict()
        payload["long_unit"] = uses
        return report
    return report


def status_payload(config: NexusConfig, ingest_id: str | None = None) -> dict[str, Any]:
    """Read-only metadata. Flag off does not read checkpoints or call a model."""
    if not config.ingest_pipeline_v2:
        return {
            "ok": True,
            "ingest_pipeline_v2": False,
            "mode": "shadow-only",
            "extraction_called": False,
            "message": "v2 off / shadow-only",
        }
    directory = checkpoint_dir(config.data_path)
    if directory.is_symlink():
        raise IngestV2Error("checkpoint directory must not be a symlink")
    paths: list[Path] = []
    if ingest_id:
        candidate = _checkpoint_path(config.data_path, ingest_id)
        if candidate.exists():
            paths = [candidate]
    elif directory.exists():
        paths = sorted(path for path in directory.glob("*.json") if path.is_file() and not path.is_symlink())
    ingests: list[dict[str, Any]] = []
    why: str | None = None
    for path in paths:
        payload = load_json(path, kind="checkpoint")
        segments = payload.get("segments")
        if not isinstance(segments, dict):
            continue
        rendered: list[dict[str, Any]] = []
        for item in segments.values():
            if not isinstance(item, dict):
                continue
            extraction = item.get("extraction") if isinstance(item.get("extraction"), dict) else {}
            failure = item.get("failure_class")
            if failure and why is None:
                why = f"segment {item.get('segment_id')} failed: {failure}"
            rendered.append(
                {
                    "segment_id": item.get("segment_id"),
                    "segment_range": [
                        item.get("start_message_index"),
                        item.get("end_message_index"),
                    ],
                    "status": item.get("status"),
                    "attempt_count": item.get("attempt_count"),
                    "started_at": item.get("started_at"),
                    "completed_at": item.get("completed_at"),
                    "content_hash": item.get("content_hash"),
                    "failure_class": failure,
                    "candidate_count": extraction.get("candidate_count", 0),
                }
            )
        ingests.append(
            {
                "ingest_id": payload.get("ingest_id"),
                "conversation_id": payload.get("conversation_id"),
                "schema_version": payload.get("schema_version"),
                "segments": rendered,
            }
        )
    return {
        "ok": True,
        "ingest_pipeline_v2": True,
        "mode": "v2",
        "paused": is_paused(config.data_path),
        "extraction_called": False,
        "why": why,
        "ingests": ingests,
    }
