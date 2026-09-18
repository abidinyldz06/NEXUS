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


class EvaluationError(NexusError):
    """A model evaluation fixture is missing, unsafe or does not match approval."""


class ReviewStoreError(NexusError):
    """The append-only review event store is invalid or unsafe."""


class VaultError(NexusError):
    """A canonical Vault operation is invalid or unsafe."""


class VaultConflictError(VaultError):
    """A Vault file changed since the caller's precondition was recorded."""


class VaultTransactionError(VaultError):
    """A Vault transaction failed and was rolled back."""


class NexusIndexError(NexusError):
    """The disposable SQLite index cannot be read or rebuilt safely."""


class CommitmentError(NexusError):
    """A commitment date or lifecycle transition is invalid."""


class PulseError(NexusError):
    """The local reminder scanner cannot complete safely."""


class RetentionError(NexusError):
    """A retention plan cannot be produced without crossing a safety boundary."""


class ForgetError(NexusError):
    """A requested forget operation cannot be completed safely."""


class PublicationError(NexusError):
    """An approved review item cannot be published safely."""


class RestoreDrillError(NexusError):
    """An isolated synthetic restore drill failed its parity checks."""


class GitRollbackDrillError(NexusError):
    """An isolated external git-dir rollback drill failed closed."""
