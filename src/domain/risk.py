"""Risk analysis: flag suspicious transactions and assign a risk level."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .enums import RiskLevel, TransactionType
from .transactions import Transaction

# Points contributed by each rule when it fires.
_LARGE_AMOUNT_POINTS = 2
_FREQUENT_POINTS = 2
_NEW_ACCOUNT_POINTS = 1
_NIGHT_POINTS = 1

_TRANSFER_TYPES = (TransactionType.TRANSFER, TransactionType.EXTERNAL_TRANSFER)


class RiskAssessment:
    """Result of analyzing a single transaction."""

    def __init__(self, transaction_id: str, level: RiskLevel, score: int, reasons: list[str]):
        self.transaction_id = transaction_id
        self.level = level
        self.score = score
        self.reasons = reasons

    def to_dict(self) -> dict:
        return {
            "transaction_id": self.transaction_id,
            "level": self.level.name,
            "score": self.score,
            "reasons": list(self.reasons),
        }

    def __str__(self) -> str:
        reasons = ", ".join(self.reasons) if self.reasons else "none"
        return f"Risk {self.level.name} (score {self.score}) | {reasons}"


class RiskAnalyzer:
    """Scores transactions against a set of heuristics and tracks recent activity."""

    def __init__(
        self,
        *,
        large_amount=10000,
        frequency_window: timedelta = timedelta(seconds=60),
        frequency_limit: int = 3,
        night_start: int = 0,
        night_end: int = 5,
    ) -> None:
        self._large_amount = Decimal(str(large_amount))
        self._frequency_window = frequency_window
        self._frequency_limit = frequency_limit
        self._night_start = night_start
        self._night_end = night_end
        self._seen_receivers: dict[str, set] = {}
        self._recent_ops: dict[str, list[datetime]] = {}

    def assess(
        self, tx: Transaction, now: datetime, *, record: bool = True
    ) -> RiskAssessment:
        """Assess a transaction's risk; optionally record it into history afterwards."""
        score = 0
        reasons: list[str] = []

        if tx.amount >= self._large_amount:
            score += _LARGE_AMOUNT_POINTS
            reasons.append(f"large amount ({tx.amount})")

        if self._night_start <= now.hour < self._night_end:
            score += _NIGHT_POINTS
            reasons.append(f"night operation ({now.hour:02d}h)")

        # Sender-keyed rules only apply when there is a sender (not deposits).
        if tx.sender is not None:
            if self._is_frequent(tx.sender, now):
                score += _FREQUENT_POINTS
                reasons.append("frequent operations")
            if tx.type in _TRANSFER_TYPES and self._is_new_receiver(tx.sender, tx.receiver):
                score += _NEW_ACCOUNT_POINTS
                reasons.append(f"transfer to new account ({tx.receiver})")

        level = self._level_for(score)
        if record:
            self._record(tx, now)
        return RiskAssessment(tx.transaction_id, level, score, reasons)

    # --- Rules -------------------------------------------------------------------------

    def _is_frequent(self, sender: str, now: datetime) -> bool:
        window_start = now - self._frequency_window
        recent = [ts for ts in self._recent_ops.get(sender, []) if ts >= window_start]
        # The current op would be the (len(recent) + 1)-th within the window.
        return len(recent) + 1 >= self._frequency_limit

    def _is_new_receiver(self, sender: str, receiver) -> bool:
        if receiver is None:
            return False
        return receiver not in self._seen_receivers.get(sender, set())

    @staticmethod
    def _level_for(score: int) -> RiskLevel:
        if score >= 3:
            return RiskLevel.HIGH
        if score >= 1:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # --- History -----------------------------------------------------------------------

    def _record(self, tx: Transaction, now: datetime) -> None:
        if tx.sender is None:
            return
        self._recent_ops.setdefault(tx.sender, []).append(now)
        if tx.receiver is not None:
            self._seen_receivers.setdefault(tx.sender, set()).add(tx.receiver)
