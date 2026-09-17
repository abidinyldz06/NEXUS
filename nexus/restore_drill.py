"""Temporary, synthetic-only restore drill for Phase 8 acceptance."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .contracts import (
    Commitment,
    DuePrecision,
    Entity,
    EntityType,
    Impact,
    Memory,
    MemoryType,
    ReviewStatus,
    Source,
    SourceRef,
    SourceType,
)
from .errors import RestoreDrillError
from .index import IndexStore, rebuild_index
from .vault import VaultRepository

_SOURCE_ID = "src_11111111111111111111111111111111"
_MEMORY_ID = "mem_22222222222222222222222222222222"
_ENTITY_ID = "ent_33333333333333333333333333333333"
_COMMITMENT_ID = "com_44444444444444444444444444444444"
_RUN_ID = "run_55555555555555555555555555555555"


@dataclass(frozen=True, slots=True)
class RestoreDrillReport:
    records: int
    open_commitments: int
    canonical_files: int
    canonical_hashes_match: bool
    index_parity: bool
    private_permissions: bool
    cleanup_verified: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": all(
                (
                    self.canonical_hashes_match,
                    self.index_parity,
                    self.private_permissions,
                    self.cleanup_verified,
                )
            ),
            "mode": "synthetic-temporary",
            "records": self.records,
            "open_commitments": self.open_commitments,
            "canonical_files": self.canonical_files,
            "canonical_hashes_match": self.canonical_hashes_match,
            "index_parity": self.index_parity,
            "private_permissions": self.private_permissions,
            "cleanup_verified": self.cleanup_verified,
            "production_paths_accessed": False,
            "production_writes": False,
            "temporary_writes": True,
        }


def _synthetic_records() -> tuple[Source | Memory | Entity | Commitment, ...]:
    span_text = "Sentetik geri yükleme kanıtı"
    source_ref = SourceRef(
        source_id=_SOURCE_ID,
        conversation_id="synthetic-restore-drill",
        span_ids=("msg_1",),
        span_sha256=sha256(span_text.encode("utf-8")).hexdigest(),
        excerpt=span_text,
    )
    source = Source(
        id=_SOURCE_ID,
        source_type=SourceType.MANUAL,
        content_sha256=sha256(b"synthetic-restore-source").hexdigest(),
        ingested_at="2026-09-17T09:00:00+03:00",
        original_name="synthetic-restore.md",
        locator="synthetic://restore-drill",
        parser={"name": "restore-drill", "version": "1"},
    )
    entity = Entity(
        id=_ENTITY_ID,
        type=EntityType.PERSON,
        display_name="Sentetik Kullanıcı",
        normalized_name="sentetik kullanıcı",
        source_refs=(source_ref,),
    )
    memory = Memory(
        id=_MEMORY_ID,
        type=MemoryType.FACT,
        summary="Sentetik restore drill kaydı",
        source_refs=(source_ref,),
        confidence=1.0,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        entity_ids=(_ENTITY_ID,),
        extractor={"model": "synthetic"},
    )
    commitment = Commitment(
        id=_COMMITMENT_ID,
        summary="Sentetik restore drill doğrulamasını tamamla",
        actor_entity_id=_ENTITY_ID,
        source_refs=(source_ref,),
        confidence=1.0,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        timezone="Europe/Istanbul",
        due_date="2026-09-18",
        due_precision=DuePrecision.DAY,
        notify=True,
    )
    return source, entity, memory, commitment


def _copy_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise RestoreDrillError("synthetic snapshot source must be a real directory")
    if destination.exists() or destination.is_symlink():
        raise RestoreDrillError("synthetic restore destination must not already exist")
    destination.mkdir(mode=0o700, parents=True)
    for current, directory_names, file_names in os.walk(source, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        destination_directory = destination / relative
        os.chmod(destination_directory, 0o700)
        for name in sorted(directory_names):
            child = current_path / name
            if child.is_symlink() or not child.is_dir():
                raise RestoreDrillError("synthetic snapshot contains an unsafe directory")
            target = destination_directory / name
            target.mkdir(mode=0o700)
        for name in sorted(file_names):
            child = current_path / name
            if child.is_symlink() or not child.is_file():
                raise RestoreDrillError("synthetic snapshot contains an unsafe file")
            target = destination_directory / name
            with child.open("rb") as source_handle, target.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle)
            os.chmod(target, 0o600)


def _manifest(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise RestoreDrillError("synthetic manifest root must be a real directory")
    result: dict[str, str] = {}
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directory_names:
            child = current_path / name
            if child.is_symlink() or not child.is_dir():
                raise RestoreDrillError("synthetic manifest contains an unsafe directory")
        for name in file_names:
            child = current_path / name
            if child.is_symlink() or not child.is_file():
                raise RestoreDrillError("synthetic manifest contains an unsafe file")
            relative = child.relative_to(root).as_posix()
            result[relative] = sha256(child.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


def _private_permissions(root: Path) -> bool:
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path.stat(follow_symlinks=False).st_mode & 0o077:
            return False
        for name in directory_names:
            child = current_path / name
            if child.is_symlink() or child.stat(follow_symlinks=False).st_mode & 0o077:
                return False
        for name in file_names:
            child = current_path / name
            if child.is_symlink() or child.stat(follow_symlinks=False).st_mode & 0o177:
                return False
    return True


def _harden_temporary_tree(root: Path) -> None:
    """Make every drill-owned directory/file private without touching external paths."""
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        if current_path.is_symlink() or not current_path.is_dir():
            raise RestoreDrillError("synthetic drill contains an unsafe directory")
        os.chmod(current_path, 0o700)
        for name in directory_names:
            child = current_path / name
            if child.is_symlink() or not child.is_dir():
                raise RestoreDrillError("synthetic drill contains an unsafe directory")
        for name in file_names:
            child = current_path / name
            if child.is_symlink() or not child.is_file():
                raise RestoreDrillError("synthetic drill contains an unsafe file")
            os.chmod(child, 0o600)


def _index_fingerprint(index_path: Path) -> str:
    with IndexStore(index_path, read_only=True) as store:
        store.require_current_schema()
        records = [
            tuple(row)
            for row in store.connection.execute(
                """
                SELECT id, kind, status, relative_path, content_sha256, payload_json
                FROM records ORDER BY id
                """
            ).fetchall()
        ]
        commitments = [
            tuple(row)
            for row in store.connection.execute(
                """
                SELECT record_id, status, due_date, due_time, timezone,
                       due_precision, notify, notified_at
                FROM commitments ORDER BY record_id
                """
            ).fetchall()
        ]
    payload = json.dumps(
        {"records": records, "commitments": commitments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def run_synthetic_restore_drill(*, temp_parent: Path | None = None) -> RestoreDrillReport:
    """Exercise snapshot/restore/rebuild parity without reading production paths."""
    if temp_parent is not None and (
        temp_parent.is_symlink() or not temp_parent.is_dir()
    ):
        raise RestoreDrillError("temporary parent must be a real directory")

    drill_root: Path | None = None
    with tempfile.TemporaryDirectory(prefix="nexus-restore-drill-", dir=temp_parent) as directory:
        drill_root = Path(directory)
        os.chmod(drill_root, 0o700)
        source_vault = drill_root / "source-vault"
        source_vault.mkdir(mode=0o700)
        repository = VaultRepository(source_vault)
        repository.commit_records(_synthetic_records(), run_id=_RUN_ID)

        snapshot_nexus = drill_root / "snapshot" / "Nexus"
        _copy_tree(source_vault / "Nexus", snapshot_nexus)
        restored_vault = drill_root / "restored-vault"
        restored_vault.mkdir(mode=0o700)
        _copy_tree(snapshot_nexus, restored_vault / "Nexus")

        source_manifest = _manifest(source_vault / "Nexus")
        snapshot_manifest = _manifest(snapshot_nexus)
        restored_manifest = _manifest(restored_vault / "Nexus")
        hashes_match = source_manifest == snapshot_manifest == restored_manifest
        if not hashes_match:
            raise RestoreDrillError("synthetic canonical hash parity failed")

        source_result = rebuild_index(source_vault, drill_root / "source-index" / "nexus.db")
        restored_result = rebuild_index(
            restored_vault, drill_root / "restored-index" / "nexus.db"
        )
        index_parity = (
            source_result.records == restored_result.records
            and source_result.open_commitments == restored_result.open_commitments
            and _index_fingerprint(source_result.index_path)
            == _index_fingerprint(restored_result.index_path)
        )
        if not index_parity:
            raise RestoreDrillError("synthetic derived-index parity failed")
        _harden_temporary_tree(drill_root)
        permissions_private = _private_permissions(drill_root)
        if not permissions_private:
            raise RestoreDrillError("synthetic drill created non-private temporary data")
        records = restored_result.records
        open_commitments = restored_result.open_commitments
        canonical_files = len(restored_manifest)

    cleanup_verified = drill_root is not None and not drill_root.exists()
    if not cleanup_verified:
        raise RestoreDrillError("synthetic drill cleanup could not be verified")
    return RestoreDrillReport(
        records=records,
        open_commitments=open_commitments,
        canonical_files=canonical_files,
        canonical_hashes_match=True,
        index_parity=True,
        private_permissions=True,
        cleanup_verified=True,
    )


__all__ = ["RestoreDrillReport", "run_synthetic_restore_drill"]
