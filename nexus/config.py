"""Configuration contract with fail-closed write readiness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigurationError


DEFAULT_INBOX_PATH = Path("~/Nexus/Inbox")
DEFAULT_DATA_PATH = Path("~/.local/share/nexus")
DEFAULT_TIMEZONE = "Europe/Istanbul"


def _expand_path(value: object, *, field_name: str, required: bool = True) -> Path | None:
    if value is None or str(value).strip() == "":
        if required:
            raise ConfigurationError(f"{field_name} is required")
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f"{field_name} must be an absolute path")
    return path


def _positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{field_name} must be a positive integer")
    return parsed


def _unit_interval(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be a number between 0 and 1")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a number between 0 and 1") from exc
    if parsed != parsed or parsed < 0 or parsed > 1:
        raise ConfigurationError(f"{field_name} must be a number between 0 and 1")
    return parsed


def _classifier_executable(value: object) -> str:
    if value is None or str(value).strip() == "":
        return "classify"
    executable = str(value).strip()
    if executable == "classify":
        return executable
    path = Path(executable)
    if path.is_absolute() and ".." not in path.parts:
        return executable
    raise ConfigurationError(
        "decision_classifier_executable must be 'classify' or an absolute path"
    )


def _boolean(value: object, *, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    raise ConfigurationError(f"{field_name} must be a boolean")


def _positive_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise ConfigurationError(f"{field_name} must be a positive number")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{field_name} must be a positive number") from exc
    if not parsed > 0 or parsed != parsed:
        raise ConfigurationError(f"{field_name} must be a positive number")
    return parsed


def _decision_timeout(value: object) -> float:
    """Classifier timeout in seconds: fast by default, hard-capped."""
    parsed = _positive_number(value, field_name="decision_timeout_seconds")
    if parsed > 15:
        raise ConfigurationError("decision_timeout_seconds must be <= 15")
    return parsed


def _relative_data_path(value: object) -> Path:
    """Shadow-log path: relative under data_path, or absolute fail-closed."""
    if value is None or str(value).strip() == "":
        return Path("logs/classifier.jsonl")
    path = Path(str(value))
    if ".." in path.parts:
        raise ConfigurationError(
            "decision_log_path must not contain '..' path segments"
        )
    if path.is_absolute():
        raise ConfigurationError(
            "decision_log_path must be relative; it resolves under data_path"
        )
    return path


@dataclass(frozen=True, slots=True)
class NexusConfig:
    """Resolved runtime configuration.

    ``vault_path`` intentionally has no default. Future mutating commands must
    refuse to run until the operator configures the exact existing Vault.
    """

    vault_path: Path | None
    inbox_path: Path = DEFAULT_INBOX_PATH.expanduser()
    data_path: Path = DEFAULT_DATA_PATH.expanduser()
    timezone: str = DEFAULT_TIMEZONE
    raw_retention_days: int = 90
    rejected_retention_days: int = 30
    max_source_bytes: int = 50 * 1024 * 1024
    source_stable_seconds: int = 5
    auto_publish_enabled: bool = False
    sensitive_auto_publish: bool = False
    ingest_pipeline_v2: bool = False
    decision_classifier_enabled: bool = False
    decision_llm_fallback_enabled: bool = False
    decision_classifier_executable: str = "classify"
    decision_high_confidence: float = 0.85
    decision_low_risk_min: float = 0.60
    decision_timeout_seconds: float = 2.5
    decision_log_enabled: bool = True
    decision_log_preview: bool = False
    decision_log_path: Path = Path("logs/classifier.jsonl")

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "NexusConfig":
        timezone = str(values.get("timezone", DEFAULT_TIMEZONE)).strip()
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(f"unknown timezone: {timezone}") from exc

        config = cls(
            vault_path=_expand_path(
                values.get("vault_path"), field_name="vault_path", required=False
            ),
            inbox_path=_expand_path(
                values.get("inbox_path", DEFAULT_INBOX_PATH), field_name="inbox_path"
            ),
            data_path=_expand_path(
                values.get("data_path", DEFAULT_DATA_PATH), field_name="data_path"
            ),
            timezone=timezone,
            raw_retention_days=_positive_int(
                values.get("raw_retention_days", 90), field_name="raw_retention_days"
            ),
            rejected_retention_days=_positive_int(
                values.get("rejected_retention_days", 30),
                field_name="rejected_retention_days",
            ),
            max_source_bytes=_positive_int(
                values.get("max_source_bytes", 50 * 1024 * 1024),
                field_name="max_source_bytes",
            ),
            source_stable_seconds=_positive_int(
                values.get("source_stable_seconds", 5),
                field_name="source_stable_seconds",
            ),
            auto_publish_enabled=_boolean(
                values.get("auto_publish_enabled", False), field_name="auto_publish_enabled"
            ),
            sensitive_auto_publish=_boolean(
                values.get("sensitive_auto_publish", False),
                field_name="sensitive_auto_publish",
            ),
            ingest_pipeline_v2=_boolean(
                values.get("ingest_pipeline_v2", False), field_name="ingest_pipeline_v2"
            ),
            decision_classifier_enabled=_boolean(
                values.get("decision_classifier_enabled", False),
                field_name="decision_classifier_enabled",
            ),
            decision_llm_fallback_enabled=_boolean(
                values.get("decision_llm_fallback_enabled", False),
                field_name="decision_llm_fallback_enabled",
            ),
            decision_classifier_executable=_classifier_executable(
                values.get("decision_classifier_executable", "classify")
            ),
            decision_high_confidence=_unit_interval(
                values.get("decision_high_confidence", 0.85),
                field_name="decision_high_confidence",
            ),
            decision_low_risk_min=_unit_interval(
                values.get("decision_low_risk_min", 0.60),
                field_name="decision_low_risk_min",
            ),
            decision_timeout_seconds=_decision_timeout(
                values.get("decision_timeout_seconds", 2.5)
            ),
            decision_log_enabled=_boolean(
                values.get("decision_log_enabled", True),
                field_name="decision_log_enabled",
            ),
            decision_log_preview=_boolean(
                values.get("decision_log_preview", False),
                field_name="decision_log_preview",
            ),
            decision_log_path=_relative_data_path(
                values.get("decision_log_path", "logs/classifier.jsonl")
            ),
        )
        if config.sensitive_auto_publish:
            raise ConfigurationError(
                "sensitive_auto_publish must remain false until encrypted/excluded "
                "backups are verified"
            )
        if config.decision_high_confidence < config.decision_low_risk_min:
            raise ConfigurationError(
                "decision_high_confidence must be greater than or equal to "
                "decision_low_risk_min"
            )
        return config

    @property
    def index_path(self) -> Path:
        return self.data_path / "nexus.db"

    @property
    def raw_path(self) -> Path:
        return self.data_path / "raw"

    @property
    def decision_log_full_path(self) -> Path:
        """Shadow log path, resolved under the private data dir."""
        return self.data_path / self.decision_log_path

    @property
    def write_ready(self) -> bool:
        return self.vault_path is not None

    def validate_existing_paths(self) -> tuple[str, ...]:
        """Return validation errors without creating directories or files."""
        errors: list[str] = []
        if self.vault_path is None:
            errors.append("vault_path is not configured")
        elif not self.vault_path.is_dir():
            errors.append(f"vault_path does not exist or is not a directory: {self.vault_path}")
        if self.inbox_path.exists() and not self.inbox_path.is_dir():
            errors.append(f"inbox_path exists but is not a directory: {self.inbox_path}")
        if self.data_path.exists() and not self.data_path.is_dir():
            errors.append(f"data_path exists but is not a directory: {self.data_path}")
        return tuple(errors)


PLUGIN_CONFIG_KEYS = (
    "vault_path",
    "inbox_path",
    "data_path",
    "timezone",
    "raw_retention_days",
    "rejected_retention_days",
    "max_source_bytes",
    "source_stable_seconds",
    "auto_publish_enabled",
    "sensitive_auto_publish",
    "ingest_pipeline_v2",
    "decision_classifier_enabled",
    "decision_llm_fallback_enabled",
    "decision_classifier_executable",
    "decision_high_confidence",
    "decision_low_risk_min",
    "decision_timeout_seconds",
    "decision_log_enabled",
    "decision_log_preview",
    "decision_log_path",
)


def from_plugin_context(ctx: Any) -> NexusConfig:
    """Read only the NEXUS plugin's namespaced settings."""
    defaults: dict[str, Any] = {
        "inbox_path": str(DEFAULT_INBOX_PATH),
        "data_path": str(DEFAULT_DATA_PATH),
        "timezone": DEFAULT_TIMEZONE,
        "raw_retention_days": 90,
        "rejected_retention_days": 30,
        "max_source_bytes": 50 * 1024 * 1024,
        "source_stable_seconds": 5,
        "auto_publish_enabled": False,
        "sensitive_auto_publish": False,
        "ingest_pipeline_v2": False,
        "decision_classifier_enabled": False,
        "decision_llm_fallback_enabled": False,
        "decision_classifier_executable": "classify",
        "decision_high_confidence": 0.85,
        "decision_low_risk_min": 0.60,
        "decision_timeout_seconds": 2.5,
        "decision_log_enabled": True,
        "decision_log_preview": False,
        "decision_log_path": "logs/classifier.jsonl",
    }
    values = {key: ctx.get_config(key, defaults.get(key)) for key in PLUGIN_CONFIG_KEYS}
    return NexusConfig.from_mapping(values)
