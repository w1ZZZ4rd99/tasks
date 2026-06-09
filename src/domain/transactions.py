"""Transaction entity."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from .enums import Currency, TransactionPriority, TransactionStatus, TransactionType
from .errors import InvalidOperationError
from .money import parse_amount, quantize_money


class Transaction:
    """A single money movement with its own lifecycle and metadata.

    ``sender``/``receiver`` are account-id strings (or ``None``). For an external transfer the
    receiver may be an opaque external reference that the bank does not resolve.
    """

    def __init__(
        self,
        tx_type: TransactionType,
        amount,
        currency: Currency,
        *,
        sender: str | None = None,
        receiver: str | None = None,
        priority: TransactionPriority = TransactionPriority.NORMAL,
        scheduled_at: datetime | None = None,
        transaction_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if not isinstance(tx_type, TransactionType):
            raise InvalidOperationError("tx_type must be a TransactionType")
        if not isinstance(currency, Currency):
            raise InvalidOperationError("currency must be a Currency")
        if not isinstance(priority, TransactionPriority):
            raise InvalidOperationError("priority must be a TransactionPriority")

        self._transaction_id = transaction_id if transaction_id else uuid.uuid4().hex[:8].upper()
        self._type = tx_type
        self._amount = parse_amount(amount)
        self._currency = currency
        self._fee = Decimal("0.00")
        self._sender = sender
        self._receiver = receiver
        self._priority = priority
        self._scheduled_at = scheduled_at
        self._status = TransactionStatus.PENDING
        self._failure_reason: str | None = None
        self._attempts = 0
        self._created_at = created_at if created_at is not None else datetime.now()
        self._processed_at: datetime | None = None

    # --- Read-only access --------------------------------------------------------------

    @property
    def transaction_id(self) -> str:
        return self._transaction_id

    @property
    def type(self) -> TransactionType:
        return self._type

    @property
    def amount(self):
        return self._amount

    @property
    def currency(self) -> Currency:
        return self._currency

    @property
    def fee(self):
        return self._fee

    @fee.setter
    def fee(self, value) -> None:
        self._fee = quantize_money(value)

    @property
    def sender(self) -> str | None:
        return self._sender

    @property
    def receiver(self) -> str | None:
        return self._receiver

    @property
    def priority(self) -> TransactionPriority:
        return self._priority

    @property
    def scheduled_at(self) -> datetime | None:
        return self._scheduled_at

    @property
    def status(self) -> TransactionStatus:
        return self._status

    @property
    def failure_reason(self) -> str | None:
        return self._failure_reason

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def processed_at(self) -> datetime | None:
        return self._processed_at

    # --- Lifecycle ---------------------------------------------------------------------

    def register_attempt(self) -> None:
        self._attempts += 1

    def mark_completed(self, at: datetime) -> None:
        self._status = TransactionStatus.COMPLETED
        self._failure_reason = None
        self._processed_at = at

    def mark_failed(self, reason: str, at: datetime) -> None:
        self._status = TransactionStatus.FAILED
        self._failure_reason = reason
        self._processed_at = at

    def mark_cancelled(self, at: datetime) -> None:
        self._status = TransactionStatus.CANCELLED
        self._processed_at = at

    def is_ready(self, now: datetime) -> bool:
        """A transaction is ready when pending and not scheduled for the future."""
        if self._status is not TransactionStatus.PENDING:
            return False
        return self._scheduled_at is None or self._scheduled_at <= now

    # --- Representation ----------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "transaction_id": self._transaction_id,
            "type": self._type.value,
            "amount": self._amount,
            "currency": self._currency.value,
            "fee": self._fee,
            "sender": self._sender,
            "receiver": self._receiver,
            "priority": self._priority.name,
            "status": self._status.value,
            "failure_reason": self._failure_reason,
            "attempts": self._attempts,
        }

    def __str__(self) -> str:
        return (
            f"Tx {self._transaction_id} | {self._type.value} | "
            f"{self._amount} {self._currency.value} | {self._status.value.upper()}"
        )
