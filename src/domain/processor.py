"""Transaction processing: fees, conversion, retries, and error logging."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Callable

from .accounts import PremiumAccount
from .enums import TransactionStatus, TransactionType
from .errors import DomainError, TransactionError
from .exchange import ExchangeRates
from .money import quantize_money
from .transactions import Transaction
from .transaction_queue import TransactionQueue


class FeePolicy:
    """Computes the service fee charged for a transaction."""

    def __init__(self, external_rate=Decimal("0.01"), min_fee=Decimal("0")) -> None:
        self._external_rate = Decimal(str(external_rate))
        self._min_fee = quantize_money(Decimal(str(min_fee)))

    def fee_for(self, tx_type: TransactionType, amount: Decimal) -> Decimal:
        """External transfers pay a percentage fee (with a floor); everything else is free."""
        if tx_type is TransactionType.EXTERNAL_TRANSFER:
            return max(quantize_money(amount * self._external_rate), self._min_fee)
        return Decimal("0.00")


class TransactionProcessor:
    """Executes transactions against a Bank, applying rules, fees, and conversion.

    Failures from business rules (``DomainError``) are terminal. Unexpected errors are treated
    as transient and retried up to ``max_retries`` times before the transaction is failed.
    """

    def __init__(
        self,
        bank,
        *,
        exchange: ExchangeRates | None = None,
        fees: FeePolicy | None = None,
        max_retries: int = 2,
        now: Callable[[], datetime] = datetime.now,
        logger: logging.Logger | None = None,
    ) -> None:
        self._bank = bank
        self._exchange = exchange or ExchangeRates()
        self._fees = fees or FeePolicy()
        self._max_retries = max_retries
        self._now = now
        self._logger = logger or logging.getLogger("bank.transactions")
        self.error_log: list[dict] = []

    def process(self, tx: Transaction) -> bool:
        """Process a single transaction; return True on success."""
        for attempt in range(self._max_retries + 1):
            tx.register_attempt()
            try:
                self._execute(tx)
            except DomainError as exc:
                # Business-rule violation: deterministic, so do not retry.
                self._record_error(tx, attempt, exc)
                tx.mark_failed(str(exc), self._now())
                return False
            except Exception as exc:  # noqa: BLE001 - transient/unexpected, retry
                self._record_error(tx, attempt, exc)
                if attempt < self._max_retries:
                    continue
                tx.mark_failed(f"failed after {tx.attempts} attempts: {exc}", self._now())
                return False
            else:
                tx.mark_completed(self._now())
                return True
        return False

    def process_queue(self, queue: TransactionQueue) -> list[Transaction]:
        """Process every ready transaction in the queue (priority order); return them."""
        processed = []
        while True:
            tx = queue.dequeue_ready()
            if tx is None:
                break
            self.process(tx)
            processed.append(tx)
        return processed

    # --- Execution ---------------------------------------------------------------------

    def _execute(self, tx: Transaction) -> None:
        if tx.type is TransactionType.DEPOSIT:
            self._bank.get_account(tx.receiver).deposit(tx.amount)
        elif tx.type is TransactionType.WITHDRAWAL:
            self._bank.get_account(tx.sender).withdraw(tx.amount)
        elif tx.type is TransactionType.TRANSFER:
            self._execute_transfer(tx)
        elif tx.type is TransactionType.EXTERNAL_TRANSFER:
            self._execute_external(tx)
        else:  # pragma: no cover - exhaustive by enum
            raise TransactionError(f"Unsupported transaction type: {tx.type}")

    def _execute_transfer(self, tx: Transaction) -> None:
        sender = self._bank.get_account(tx.sender)
        receiver = self._bank.get_account(tx.receiver)
        self._check_transfer_allowed(sender)
        sender.withdraw(tx.amount)
        credit = self._exchange.convert(tx.amount, sender.currency, receiver.currency)
        receiver.deposit(credit)

    def _execute_external(self, tx: Transaction) -> None:
        sender = self._bank.get_account(tx.sender)
        fee = self._fees.fee_for(tx.type, tx.amount)
        tx.fee = fee
        self._check_transfer_allowed(sender)
        # Amount plus fee leaves the bank; there is no internal account to credit.
        sender.withdraw(tx.amount + fee)

    @staticmethod
    def _check_transfer_allowed(sender) -> None:
        """Forbid transferring from a negative balance unless the account is premium."""
        if sender.balance < 0 and not isinstance(sender, PremiumAccount):
            raise TransactionError(
                f"Account {sender.account_id} has a negative balance; transfer not allowed"
            )

    # --- Logging -----------------------------------------------------------------------

    def _record_error(self, tx: Transaction, attempt: int, exc: Exception) -> None:
        entry = {
            "transaction_id": tx.transaction_id,
            "attempt": attempt + 1,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        self.error_log.append(entry)
        self._logger.warning(
            "transaction %s failed on attempt %s: %s: %s",
            tx.transaction_id,
            attempt + 1,
            type(exc).__name__,
            exc,
        )
