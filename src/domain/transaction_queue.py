"""Priority queue for pending transactions, with deferral and cancellation."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from .errors import InvalidOperationError
from .enums import TransactionStatus
from .transactions import Transaction


class TransactionQueue:
    """Holds pending transactions and serves the highest-priority ready one first.

    Deferred transactions (a future ``scheduled_at``) are not served until their time comes.
    The clock is injectable so deferral is unit-testable.
    """

    def __init__(self, *, now: Callable[[], datetime] = datetime.now) -> None:
        self._items: list[Transaction] = []
        self._now = now

    def add(self, transaction: Transaction) -> None:
        if transaction.status is not TransactionStatus.PENDING:
            raise InvalidOperationError("Only pending transactions can be queued")
        self._items.append(transaction)

    def cancel(self, transaction_id: str) -> bool:
        """Cancel a queued transaction by id; return True if it was found."""
        for tx in self._items:
            if tx.transaction_id == transaction_id:
                tx.mark_cancelled(self._now())
                self._items.remove(tx)
                return True
        return False

    @property
    def pending(self) -> list[Transaction]:
        return [tx for tx in self._items if tx.status is TransactionStatus.PENDING]

    def __len__(self) -> int:
        return len(self._items)

    def dequeue_ready(self) -> Transaction | None:
        """Remove and return the highest-priority ready transaction, or None."""
        now = self._now()
        ready = [tx for tx in self._items if tx.is_ready(now)]
        if not ready:
            return None
        # Highest priority first; ties broken by creation time (FIFO).
        ready.sort(key=lambda tx: (-tx.priority.value, tx.created_at))
        chosen = ready[0]
        self._items.remove(chosen)
        return chosen
