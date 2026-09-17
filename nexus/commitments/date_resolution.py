"""Conservative Turkish date resolution for commitment candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..contracts import DuePrecision
from ..errors import CommitmentError

_ISO_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_LOCAL_DATE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)")
_COLON_TIME = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)")
_NAMED_TIME = re.compile(r"\bsaat\s+([01]?\d|2[0-3])[.:]([0-5]\d)(?!\d)")
_WEEKDAYS = {
    "pazartesi": 0,
    "salı": 1,
    "çarşamba": 2,
    "perşembe": 3,
    "cuma": 4,
    "cumartesi": 5,
    "pazar": 6,
}
_AMBIGUOUS_TERMS = ("yakında", "bir ara", "sonra", "ileride", "müsait olunca")


@dataclass(frozen=True, slots=True)
class DateResolution:
    due_date: str | None
    due_time: str | None
    due_precision: DuePrecision
    timezone: str
    reason: str

    @property
    def schedulable(self) -> bool:
        return self.due_date is not None and self.due_precision is not DuePrecision.AMBIGUOUS


def _parse_source_at(value: str | datetime, timezone: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise CommitmentError("source_at must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        raise CommitmentError("source_at must include a timezone offset")
    return parsed.astimezone(timezone)


def _extract_date(text: str, local_source: datetime) -> tuple[date | None, str]:
    iso_match = _ISO_DATE.search(text)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1)), "explicit_date"
        except ValueError:
            return None, "invalid_date"
    local_match = _LOCAL_DATE.search(text)
    if local_match:
        day, month, year = (int(value) for value in local_match.groups())
        try:
            return date(year, month, day), "explicit_date"
        except ValueError:
            return None, "invalid_date"
    if "bugün" in text:
        return local_source.date(), "today"
    if "yarın" in text:
        return local_source.date() + timedelta(days=1), "tomorrow"
    for name, weekday in _WEEKDAYS.items():
        if re.search(rf"\b{re.escape(name)}\b", text):
            days_ahead = (weekday - local_source.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return local_source.date() + timedelta(days=days_ahead), "weekday"
    return None, "missing_date"


def _extract_time(text: str) -> str | None:
    match = _COLON_TIME.search(text) or _NAMED_TIME.search(text)
    if match is None:
        return None
    hour, minute = (int(value) for value in match.groups())
    return f"{hour:02d}:{minute:02d}:00"


def resolve_due(
    statement: str,
    *,
    source_at: str | datetime,
    timezone: str = "Europe/Istanbul",
) -> DateResolution:
    """Resolve only explicit dates, today/tomorrow and Turkish weekday names."""
    if not isinstance(statement, str) or not statement.strip():
        raise CommitmentError("statement must not be empty")
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise CommitmentError(f"unknown timezone: {timezone}") from exc
    local_source = _parse_source_at(source_at, zone)
    normalized = " ".join(statement.casefold().split())
    due_date, reason = _extract_date(normalized, local_source)
    due_time = _extract_time(normalized)
    if due_date is None:
        if any(term in normalized for term in _AMBIGUOUS_TERMS):
            reason = "ambiguous_relative_date"
        return DateResolution(None, due_time, DuePrecision.AMBIGUOUS, timezone, reason)
    precision = DuePrecision.EXACT if due_time is not None else DuePrecision.DAY
    return DateResolution(due_date.isoformat(), due_time, precision, timezone, reason)
