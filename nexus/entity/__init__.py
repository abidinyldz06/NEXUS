"""Deterministic entity resolution without fuzzy auto-merge."""

from .resolver import EntityResolution, EntityResolver, ResolutionStatus, normalize_alias

__all__ = ["EntityResolution", "EntityResolver", "ResolutionStatus", "normalize_alias"]
