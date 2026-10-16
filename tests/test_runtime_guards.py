"""Path containment, isolated plugin cache, and SQLite durability guards."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from nexus.errors import VaultError
from nexus.ids import IdPrefix, new_id
from nexus.index.store import IndexStore, configure_sqlite
from nexus.vault.paths import resolve_safe_vault_path
from nexus.vault.transaction import VaultTransaction, VaultWrite

try:
    from fastapi import FastAPI
except ImportError:
    FastAPI = None


class SafeVaultPathTests(unittest.TestCase):
    def test_relative_path_stays_inside_the_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            resolved = resolve_safe_vault_path(base, Path("Nexus") / "Memory" / "note.md")
            self.assertTrue(resolved.is_relative_to(base.resolve()))
            self.assertEqual("note.md", resolved.name)

    def test_parent_segments_and_outside_absolute_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            outside = base.parent / "outside.md"
            for target in (Path("..") / "outside.md", outside, Path("Nexus") / ".." / "outside.md"):
                with self.subTest(target=str(target)), self.assertRaises(VaultError):
                    resolve_safe_vault_path(base, target)
            self.assertFalse(outside.exists())

    def test_symlink_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            outside = Path(tempfile.mkdtemp(prefix="escaped-", dir=base.parent))
            link = base / "alias"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(VaultError):
                resolve_safe_vault_path(base, Path("alias") / "note.md")
            self.assertFalse((outside / "note.md").exists())

    def test_transaction_refuses_traversal_and_publishes_by_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            outside = vault.parent / "leaked.md"
            transaction = VaultTransaction(vault)
            with self.assertRaises(VaultError):
                transaction.commit(
                    (VaultWrite(Path("Nexus") / ".." / outside.name, b"leak"),),
                    run_id=new_id(IdPrefix.RUN),
                )
            self.assertFalse(outside.exists())
            payload = b"canonical-markdown\n"
            result = transaction.commit(
                (VaultWrite(Path("Nexus") / "Memory" / "note.md", payload),),
                run_id=new_id(IdPrefix.RUN),
            )
            published = vault / "Nexus" / "Memory" / "note.md"
            self.assertEqual(payload, published.read_bytes())
            self.assertEqual(("Nexus/Memory/note.md",), result.written_paths)
            self.assertFalse((vault / "Nexus" / "Memory" / "note.md.tmp").exists())


class SqliteGuardTests(unittest.TestCase):
    def test_writable_and_read_only_connections_keep_the_lock_pragmas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.db"
            with IndexStore(path) as store:
                store.migrate()
                mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
                self.assertEqual("wal", mode)
                self.assertEqual(1, store.connection.execute("PRAGMA synchronous").fetchone()[0])
                self.assertGreaterEqual(
                    store.connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000
                )
            with IndexStore(path, read_only=True) as store:
                self.assertGreaterEqual(
                    store.connection.execute("PRAGMA busy_timeout").fetchone()[0], 5000
                )
                self.assertEqual(1, store.connection.execute("PRAGMA foreign_keys").fetchone()[0])

    def test_configure_sqlite_sets_wal_before_a_write_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.db"
            connection = sqlite3.connect(path)
            try:
                configure_sqlite(connection, writable=True)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE holds (id TEXT)")
                connection.execute("COMMIT")
                self.assertEqual("wal", connection.execute("PRAGMA journal_mode").fetchone()[0])
                self.assertEqual(1, connection.execute("PRAGMA synchronous").fetchone()[0])
            finally:
                connection.close()


@unittest.skipIf(FastAPI is None, "FastAPI is supplied by the Hermes runtime")
class IsolatedCoreCacheTests(unittest.TestCase):
    def test_reloading_the_dashboard_module_reuses_one_package(self) -> None:
        api_path = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
        before = {key for key in sys.modules if key.startswith("_hermes_nexus_hub_")}

        def load(name: str) -> object:
            spec = importlib.util.spec_from_file_location(name, api_path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            self.addCleanup(sys.modules.pop, name, None)
            spec.loader.exec_module(module)
            return module

        first = load("nexus_runtime_guard_api_a")
        after_first = {key for key in sys.modules if key.startswith("_hermes_nexus_hub_")}
        second = load("nexus_runtime_guard_api_b")
        after_second = {key for key in sys.modules if key.startswith("_hermes_nexus_hub_")}
        self.assertEqual(after_first, after_second)
        self.assertLessEqual(len(before), len(after_first))
        self.assertIs(first._config_module, second._config_module)
        self.assertEqual(1, len({key.split(".", 1)[0] for key in after_second}))
