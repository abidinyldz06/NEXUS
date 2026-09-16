"""NEXUS domain errors."""


class NexusError(Exception):
    """Base class for expected NEXUS failures."""


class ConfigurationError(NexusError):
    """Configuration is missing or unsafe."""


class ContractError(NexusError):
    """A versioned data contract is invalid."""


class SourceError(NexusError):
    """A source cannot be discovered, parsed or normalized safely."""


class UnsafeSourceError(SourceError):
    """A source violates a path, size or file-safety boundary."""


class ParseError(SourceError):
    """A supported source has malformed or unsupported content."""


class StateError(NexusError):
    """Private ingestion state is corrupt or cannot be updated safely."""


class HermesExportError(SourceError):
    """The official Hermes export command could not run safely."""


class ExtractionError(NexusError):
    """Structured extraction failed without producing a trusted result."""


class ReviewStoreError(NexusError):
    """The append-only review event store is invalid or unsafe."""
