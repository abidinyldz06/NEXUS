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
        )
        if config.sensitive_auto_publish:
            raise ConfigurationError(
                "sensitive_auto_publish must remain false until encrypted/excluded "
                "backups are verified"
            )
        return config

    @property
    def index_path(self) -> Path:
        return self.data_path / "nexus.db"

    @property
    def raw_path(self) -> Path:
        return self.data_path / "raw"

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
    }
    values = {key: ctx.get_config(key, defaults.get(key)) for key in PLUGIN_CONFIG_KEYS}
    return NexusConfig.from_mapping(values)
