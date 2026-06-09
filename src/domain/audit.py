"""Structured audit log with severity levels, file persistence, and filtering."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Callable

from .enums import AuditSeverity


def _json_safe(value):
    """Convert audit values into JSON-serializable forms."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class AuditEvent:
    """A single recorded audit event."""

    def __init__(
        self,
        timestamp: datetime,
        severity: AuditSeverity,
        action: str,
        message: str,
        metadata: dict | None = None,
    ) -> None:
        self.timestamp = timestamp
        self.severity = severity
        self.action = action
        self.message = message
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity.name,
            "action": self.action,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }

    def __str__(self) -> str:
        return f"[{self.severity.name}] {self.action}: {self.message}"


class AuditLog:
    """Keeps audit events in memory and, optionally, appends them to a file."""

    def __init__(
        self, *, file_path: str | None = None, now: Callable[[], datetime] = datetime.now
    ) -> None:
        self._events: list[AuditEvent] = []
        self._file_path = file_path
        self._now = now

    def log(
        self, severity: AuditSeverity, action: str, message: str, **metadata
    ) -> AuditEvent:
        event = AuditEvent(self._now(), severity, action, message, metadata)
        self._events.append(event)
        if self._file_path:
            with open(self._file_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict()) + "\n")
        return event

    @property
    def entries(self) -> list[AuditEvent]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def filter(
        self,
        *,
        min_severity: AuditSeverity | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        predicate: Callable[[AuditEvent], bool] | None = None,
    ) -> list[AuditEvent]:
        """Return events matching every provided criterion."""
        result = []
        for event in self._events:
            if min_severity is not None and event.severity.value < min_severity.value:
                continue
            if action is not None and event.action != action:
                continue
            if since is not None and event.timestamp < since:
                continue
            if until is not None and event.timestamp > until:
                continue
            if predicate is not None and not predicate(event):
                continue
            result.append(event)
        return result

    def export(self, path: str) -> None:
        """Write all events to ``path`` as one JSON object per line."""
        with open(path, "w", encoding="utf-8") as fh:
            for event in self._events:
                fh.write(json.dumps(event.to_dict()) + "\n")
