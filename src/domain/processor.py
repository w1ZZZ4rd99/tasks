"""Transaction processing: fees, conversion, retries, and error logging."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Callable

from .accounts import PremiumAccount
from .audit import AuditLog
from .enums import AuditSeverity, RiskLevel, TransactionType
from .errors import DomainError, TransactionError
from .exchange import ExchangeRates
from .money import quantize_money
from .risk import RiskAnalyzer
from .transactions import Transaction
from .transaction_queue import TransactionQueue

# Maps a risk level to the severity used when auditing its assessment.
_RISK_SEVERITY = {
    RiskLevel.LOW: AuditSeverity.INFO,
    RiskLevel.MEDIUM: AuditSeverity.WARNING,
    RiskLevel.HIGH: AuditSeverity.CRITICAL,
}


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
        audit: AuditLog | None = None,
        risk: RiskAnalyzer | None = None,
        block_at: RiskLevel = RiskLevel.HIGH,
    ) -> None:
        self._bank = bank
        self._exchange = exchange or ExchangeRates()
        self._fees = fees or FeePolicy()
        self._max_retries = max_retries
        self._now = now
        self._logger = logger or logging.getLogger("bank.transactions")
        self.error_log: list[dict] = []
        self.history: list[Transaction] = []
        # Use `is None` (not `or`): an empty AuditLog is falsy via __len__.
        self.audit = audit if audit is not None else AuditLog(now=now)
        self._risk = risk
        self._block_at = block_at

    def process(self, tx: Transaction) -> bool:
        """Process a single transaction; return True on success."""
        # Record every processed transaction; the stored reference tracks its final status.
        self.history.append(tx)

        if self._risk is not None and self._risk_blocks(tx):
            return False

        for attempt in range(self._max_retries + 1):
            tx.register_attempt()
            try:
                self._execute(tx)
            except DomainError as exc:
                # Business-rule violation: deterministic, so do not retry.
                self._record_error(tx, attempt, exc)
                tx.mark_failed(str(exc), self._now())
                self._audit_failure(tx, exc)
                return False
            except Exception as exc:  # noqa: BLE001 - transient/unexpected, retry
                self._record_error(tx, attempt, exc)
                if attempt < self._max_retries:
                    continue
                tx.mark_failed(f"failed after {tx.attempts} attempts: {exc}", self._now())
                self._audit_failure(tx, exc)
                return False
            else:
                tx.mark_completed(self._now())
                self.audit.log(
                    AuditSeverity.INFO, "transaction.completed",
                    f"{tx.type.value} {tx.amount} {tx.currency.value} completed",
                    **self._tx_metadata(tx),
                )
                return True
        return False

    def _risk_blocks(self, tx: Transaction) -> bool:
        """Assess risk, audit it, and block the transaction when it is too risky."""
        assessment = self._risk.assess(tx, self._now())
        self.audit.log(
            _RISK_SEVERITY[assessment.level], "risk.assessed", str(assessment),
            risk_level=assessment.level, score=assessment.score,
            reasons=assessment.reasons, **self._tx_metadata(tx),
        )
        if assessment.level.value < self._block_at.value:
            return False
        tx.register_attempt()
        reason = "blocked by risk analysis: " + ", ".join(assessment.reasons)
        tx.mark_failed(reason, self._now())
        self.audit.log(
            AuditSeverity.CRITICAL, "transaction.blocked", reason,
            risk_level=assessment.level, reasons=assessment.reasons,
            error_type="RiskBlocked", **self._tx_metadata(tx),
        )
        return True

    def _audit_failure(self, tx: Transaction, exc: Exception) -> None:
        self.audit.log(
            AuditSeverity.WARNING, "transaction.failed", str(exc),
            error_type=type(exc).__name__, **self._tx_metadata(tx),
        )

    @staticmethod
    def _tx_metadata(tx: Transaction) -> dict:
        return {
            "transaction_id": tx.transaction_id,
            "type": tx.type.value,
            "sender": tx.sender,
            "receiver": tx.receiver,
            "amount": tx.amount,
            "currency": tx.currency.value,
        }

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
        # Money movements obey the same nightly lockout as account management.
        self._bank.ensure_business_hours()
        if tx.type is TransactionType.DEPOSIT:
            receiver = self._bank.get_account(tx.receiver)
            receiver.deposit(self._to_account_currency(tx.amount, tx, receiver))
        elif tx.type is TransactionType.WITHDRAWAL:
            sender = self._bank.get_account(tx.sender)
            sender.withdraw(self._to_account_currency(tx.amount, tx, sender))
        elif tx.type is TransactionType.TRANSFER:
            self._execute_transfer(tx)
        elif tx.type is TransactionType.EXTERNAL_TRANSFER:
            self._execute_external(tx)
        else:  # pragma: no cover - exhaustive by enum
            raise TransactionError(f"Unsupported transaction type: {tx.type}")

    def _to_account_currency(self, amount: Decimal, tx: Transaction, account) -> Decimal:
        """Convert an amount denominated in the transaction's currency to the account's."""
        return self._exchange.convert(amount, tx.currency, account.currency)

    def _execute_transfer(self, tx: Transaction) -> None:
        sender = self._bank.get_account(tx.sender)
        receiver = self._bank.get_account(tx.receiver)
        self._check_transfer_allowed(sender)
        debit = self._to_account_currency(tx.amount, tx, sender)
        credit = self._to_account_currency(tx.amount, tx, receiver)
        balance_before = sender.balance
        sender.withdraw(debit)
        try:
            receiver.deposit(credit)
        except DomainError:
            # Keep the transfer atomic: put back exactly what the withdrawal took
            # (including any account-level fees) before propagating the failure.
            sender.deposit(balance_before - sender.balance)
            raise

    def _execute_external(self, tx: Transaction) -> None:
        sender = self._bank.get_account(tx.sender)
        self._check_transfer_allowed(sender)
        # The fee is denominated in the transaction currency, like the amount.
        fee = self._fees.fee_for(tx.type, tx.amount)
        tx.fee = fee
        # Amount plus fee leaves the bank; there is no internal account to credit.
        sender.withdraw(self._to_account_currency(tx.amount + fee, tx, sender))

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
