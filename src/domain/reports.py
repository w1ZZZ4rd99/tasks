"""Audit reports derived from an AuditLog."""

from __future__ import annotations

from .audit import AuditEvent, AuditLog
from .enums import AuditSeverity, RiskLevel

_RISKY_LEVELS = {RiskLevel.MEDIUM.name, RiskLevel.HIGH.name}


class AuditReporter:
    """Builds analytical reports from recorded audit events."""

    def __init__(self, audit_log: AuditLog) -> None:
        self._audit = audit_log

    def suspicious_operations(self) -> list[AuditEvent]:
        """Events that are either warning+ severity or flagged at medium/high risk."""
        def is_suspicious(event: AuditEvent) -> bool:
            if event.severity.value >= AuditSeverity.WARNING.value:
                return True
            level = event.metadata.get("risk_level")
            return _level_name(level) in _RISKY_LEVELS

        return [e for e in self._audit.entries if is_suspicious(e)]

    def client_risk_profile(self, bank, client_id: str) -> dict:
        """Aggregate the risk picture for one client across their accounts."""
        client = bank.get_client(client_id)
        owned = set(client.account_numbers)

        counts = {level.name: 0 for level in RiskLevel}
        reasons: set[str] = set()
        highest = RiskLevel.LOW
        assessed = 0

        for event in self._audit.entries:
            if event.action != "risk.assessed":
                continue
            if event.metadata.get("sender") not in owned and \
                    event.metadata.get("receiver") not in owned:
                continue
            assessed += 1
            level_name = _level_name(event.metadata.get("risk_level"))
            if level_name in counts:
                counts[level_name] += 1
                if RiskLevel[level_name].value > highest.value:
                    highest = RiskLevel[level_name]
            reasons.update(event.metadata.get("reasons", []))

        return {
            "client_id": client.client_id,
            "full_name": client.full_name,
            "assessed_operations": assessed,
            "counts_by_level": counts,
            "highest_level": highest.name,
            "reasons": sorted(reasons),
        }

    def error_statistics(self) -> dict:
        """Counts of failed/blocked operations grouped by error type."""
        by_type: dict[str, int] = {}
        total = 0
        for event in self._audit.entries:
            if event.action not in ("transaction.failed", "transaction.blocked"):
                continue
            total += 1
            error_type = event.metadata.get("error_type", "Unknown")
            by_type[error_type] = by_type.get(error_type, 0) + 1
        return {"total_errors": total, "by_type": by_type}


def _level_name(level) -> str | None:
    """Normalize a risk level (enum or name) to its string name."""
    if isinstance(level, RiskLevel):
        return level.name
    return level
