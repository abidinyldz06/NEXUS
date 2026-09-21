"""Live-route categories. Separate from memory extraction CandidateKind."""

from __future__ import annotations

from enum import StrEnum


class RouteCategory(StrEnum):
    COMMAND = "command"
    CHAT = "chat"
    TASK = "task"
    TEMPORARY_INFORMATION = "temporary_information"
    DURABLE_MEMORY = "durable_memory"
    REMINDER = "reminder"
    CUSTOMER_OR_CRM = "customer_or_crm"
    UNKNOWN = "unknown"


CLASSIFIER_LABELS: tuple[RouteCategory, ...] = tuple(RouteCategory)
