"""Disposable SQLite search index derived from canonical Vault records."""

from .rebuild import RebuildResult, rebuild_index
from .search import SearchResult, search_index
from .store import IndexStore

__all__ = ["IndexStore", "RebuildResult", "SearchResult", "rebuild_index", "search_index"]
