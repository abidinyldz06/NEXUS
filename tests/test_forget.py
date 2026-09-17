from __future__ import annotations

import json
import os
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from nexus.config import NexusConfig
from nexus.contracts import Impact, Memory, MemoryType, ReviewStatus, SourceRef
from nexus.errors import ForgetError, NexusIndexError
from nexus.forget import apply_forget, plan_forget
from nexus.ids import IdPrefix, new_id
from nexus.index import rebuild_index, search_index
from nexus.vault import VaultRepository
from nexus.vault.rebuild_views import current_memory_view_write


def _memory(index: int, *, supersedes: tuple[str, ...] = ()) -> Memory:
    span_id = f"msg_{index}"
    return Memory(
        id=new_id(IdPrefix.MEMORY),
        type=MemoryType.FACT,
        summary=f"Sentetik unutma kaydı {index}",
        source_refs=(
            SourceRef(
                source_id=new_id(IdPrefix.SOURCE),
                conversation_id=f"conversation-{index}",
                span_ids=(span_id,),
                span_sha256=sha256(span_id.encode()).hexdigest(),
            ),
        ),
        confidence=0.95,
        impact=Impact.LOW,
        review_status=ReviewStatus.APPROVED,
        supersedes=supersedes,
        extractor={"model": "fixture"},
    )


def _config(root: Path) -> NexusConfig:
    vault = root / "vault"
    data = root / "private"
    vault.mkdir()
    return NexusConfig.from_mapping(
        {
            "vault_path": str(vault),
            "data_path": str(data),
            "index_path": str(data / "nexus.db"),
        }
    )


def _seed(config: NexusConfig, memories: tuple[Memory, ...]) -> VaultRepository:
    assert config.vault_path is not None
    repository = VaultRepository(config.vault_path)
    repository.commit_records(
        memories,
        run_id=new_id(IdPrefix.RUN),
        generated_writes=(current_memory_view_write(memories, repository),),
    )
    rebuild_index(config.vault_path, config.index_path)
    return repository


class ForgetTests(unittest.TestCase):
    def test_dry_run_reports_dependencies_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            target = _memory(1)
            dependent = _memory(2, supersedes=(target.id,))
            repository = _seed(config, (target, dependent))
            assert config.vault_path is not None
            target_path = config.vault_path / repository.record_path(target)
            before = target_path.read_bytes()

            plan = plan_forget(config, target.id)

            self.assertFalse(plan.can_apply)
            self.assertEqual(1, plan.dependency_count)
            self.assertEqual({"memory": 1}, plan.dependency_kinds)
            self.assertEqual(before, target_path.read_bytes())
            with self.assertRaisesRegex(ForgetError, "dependent records"):
                apply_forget(config, target.id, confirmation=target.id)

    def test_confirmed_forget_deletes_target_updates_view_index_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            target = _memory(1)
            retained = _memory(2)
            repository = _seed(config, (target, retained))
            assert config.vault_path is not None
            target_path = config.vault_path / repository.record_path(target)

            result = apply_forget(config, target.id, confirmation=target.id)

            self.assertFalse(target_path.exists())
            self.assertEqual(1, result.records_after)
            self.assertEqual((), search_index(config.index_path, target.summary))
            self.assertEqual(1, len(search_index(config.index_path, retained.summary)))
            view = (config.vault_path / "Nexus/Views/Current-Memory.md").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(target.id, view)
            self.assertIn(retained.id, view)
            audit_path = config.data_path / "forget/events.jsonl"
            event = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(target.id, event["record_id"])
            self.assertNotIn(target.summary, audit_path.read_text(encoding="utf-8"))
            self.assertEqual(0o600, os.stat(audit_path).st_mode & 0o777)

    def test_confirmation_mismatch_and_rebuild_failure_preserve_exact_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            target = _memory(1)
            repository = _seed(config, (target,))
            assert config.vault_path is not None
            target_path = config.vault_path / repository.record_path(target)
            view_path = config.vault_path / "Nexus/Views/Current-Memory.md"
            before = (
                target_path.read_bytes(),
                view_path.read_bytes(),
                config.index_path.read_bytes(),
            )

            with self.assertRaisesRegex(ForgetError, "exactly match"):
                apply_forget(config, target.id, confirmation=new_id(IdPrefix.MEMORY))

            def failing_rebuild(vault_path: Path, index_path: Path):
                raise NexusIndexError("injected rebuild failure")

            with self.assertRaisesRegex(ForgetError, "exact prior state was restored"):
                apply_forget(
                    config,
                    target.id,
                    confirmation=target.id,
                    rebuild=failing_rebuild,
                )

            self.assertEqual(before[0], target_path.read_bytes())
            self.assertEqual(before[1], view_path.read_bytes())
            self.assertEqual(before[2], config.index_path.read_bytes())
            self.assertFalse((config.data_path / "forget/events.jsonl").exists())

            with patch("nexus.forget._append_audit", side_effect=OSError("audit failure")):
                with self.assertRaisesRegex(ForgetError, "exact prior state was restored"):
                    apply_forget(config, target.id, confirmation=target.id)

            self.assertEqual(before[0], target_path.read_bytes())
            self.assertEqual(before[1], view_path.read_bytes())
            self.assertEqual(before[2], config.index_path.read_bytes())

    def test_rollback_never_overwrites_a_concurrent_target_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = _config(Path(directory))
            target = _memory(1)
            repository = _seed(config, (target,))
            assert config.vault_path is not None
            target_path = config.vault_path / repository.record_path(target)

            def concurrent_change(*args, **kwargs):
                target_path.write_text("external concurrent change", encoding="utf-8")
                raise OSError("audit failure after concurrent change")

            with patch("nexus.forget._append_audit", side_effect=concurrent_change):
                with self.assertRaisesRegex(ForgetError, "rollback was incomplete: target"):
                    apply_forget(config, target.id, confirmation=target.id)

            self.assertEqual(
                "external concurrent change", target_path.read_text(encoding="utf-8")
            )
            self.assertFalse((config.data_path / "forget/events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
