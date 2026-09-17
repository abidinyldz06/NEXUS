"""Fixed-path repository for canonical NEXUS Vault records."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from ..contracts import (
    Commitment,
    Entity,
    EntityType,
    Memory,
    MemoryType,
    Relation,
    ReviewItem,
    ReviewStatus,
    Source,
)
from ..errors import VaultError
from ..fingerprints import sha256_bytes
from .renderer import render_record
from .transaction import TransactionResult, VaultTransaction, VaultWrite

CanonicalRecord = Source | Memory | Entity | Relation | Commitment | ReviewItem

_MEMORY_DIRECTORIES = {
    MemoryType.FACT: "Facts",
    MemoryType.EVENT: "Events",
    MemoryType.DECISION: "Decisions",
    MemoryType.PREFERENCE: "Preferences",
}
_ENTITY_DIRECTORIES = {
    EntityType.PERSON: "People",
    EntityType.ORGANIZATION: "Organizations",
    EntityType.PROJECT: "Projects",
    EntityType.ASSET: "Assets",
    EntityType.PLACE: "Places",
}


def _written_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class VaultRepository:
    """Map validated contracts to generated paths below one Vault's Nexus namespace."""

    def __init__(
        self,
        vault_root: Path,
        *,
        transaction_factory: type[VaultTransaction] = VaultTransaction,
    ) -> None:
        self.vault_root = vault_root
        self.transaction_factory = transaction_factory

    def record_path(self, record: CanonicalRecord) -> Path:
        if isinstance(record, Memory):
            return Path("Nexus/Memory") / _MEMORY_DIRECTORIES[record.type] / f"{record.id}.md"
        if isinstance(record, Entity):
            return Path("Nexus/Entities") / _ENTITY_DIRECTORIES[record.type] / f"{record.id}.md"
        if isinstance(record, Relation):
            return Path("Nexus/Relations") / f"{record.id}.md"
        if isinstance(record, Commitment):
            return Path("Nexus/Commitments") / f"{record.id}.md"
        if isinstance(record, Source):
            return Path("Nexus/Sources") / f"{record.id}.md"
        if isinstance(record, ReviewItem):
            directory = self._review_directory(record.status)
            return Path("Nexus/Review") / directory / f"{record.id}.md"
        raise VaultError(f"unsupported canonical record type: {type(record).__name__}")

    def prepare_record(
        self,
        record: CanonicalRecord,
        *,
        run_id: str,
        written_at: str,
        expected_sha256: str | None = None,
    ) -> VaultWrite:
        self._require_provenance(record)
        content = render_record(record, run_id=run_id, written_at=written_at).encode("utf-8")
        return VaultWrite(self.record_path(record), content, expected_sha256)

    def commit_records(
        self,
        records: Iterable[CanonicalRecord],
        *,
        run_id: str,
        expected_hashes: dict[str, str] | None = None,
        generated_writes: tuple[VaultWrite, ...] = (),
        transaction: VaultTransaction | None = None,
    ) -> TransactionResult:
        expected = expected_hashes or {}
        written_at = _written_at()
        writes = tuple(
            self.prepare_record(
                record,
                run_id=run_id,
                written_at=written_at,
                expected_sha256=expected.get(record.id),
            )
            for record in records
        ) + generated_writes
        runner = transaction or self.transaction_factory(self.vault_root)
        return runner.commit(writes, run_id=run_id)

    def current_hash(self, record: CanonicalRecord) -> str:
        path = self.vault_root / self.record_path(record)
        if path.is_symlink() or not path.is_file():
            raise VaultError("canonical record does not exist as a regular file")
        return sha256_bytes(path.read_bytes())

    @staticmethod
    def _review_directory(status: ReviewStatus) -> str:
        if status is ReviewStatus.PENDING:
            return "Pending"
        if status in {ReviewStatus.APPROVED, ReviewStatus.EDITED, ReviewStatus.AUTO}:
            return "Approved"
        return "Rejected"

    @staticmethod
    def _require_provenance(record: CanonicalRecord) -> None:
        if isinstance(record, Source):
            return
        if not record.source_refs:
            raise VaultError("derived canonical records require at least one source_ref")
