"""Core domain models for bank accounts.

An abstract account base encapsulates shared state and validation; ``BankAccount`` is the
concrete type. Monetary values use :class:`decimal.Decimal` for correct money arithmetic
(binary floats cannot represent values like ``0.10`` exactly).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from enum import Enum

from .errors import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)

# Two decimal places is enough for the currencies we support.
_MONEY_QUANT = Decimal("0.01")


class Currency(Enum):
    """Supported account currencies."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    KZT = "KZT"
    CNY = "CNY"


class AccountStatus(Enum):
    """Lifecycle status of an account; only ``ACTIVE`` accounts may transact."""

    ACTIVE = "active"
    FROZEN = "frozen"
    CLOSED = "closed"


class AbstractAccount(ABC):
    """Abstract base for every account type.

    Holds the state shared by all accounts (id, owner, balance, status, currency) and the
    reusable validation helpers. Subclasses implement the actual operations so that different
    account types can apply their own rules (overdraft, interest, fees, ...).
    """

    def __init__(
        self,
        owner: str,
        account_id: str,
        balance: Decimal,
        status: AccountStatus,
        currency: Currency,
    ) -> None:
        self._owner = owner
        self._account_id = account_id
        self._balance = balance
        self._status = status
        self._currency = currency

    # --- Read-only access (encapsulation: no direct mutation of _balance) -------------

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def balance(self) -> Decimal:
        return self._balance

    @property
    def status(self) -> AccountStatus:
        return self._status

    @property
    def currency(self) -> Currency:
        return self._currency

    # --- Shared validation reused by subclasses ---------------------------------------

    def _validate_amount(self, amount) -> Decimal:
        """Normalize and validate an operation amount.

        Returns the amount as a quantized ``Decimal``. Rejects non-numeric input, NaN, zero,
        and negative values with :class:`InvalidOperationError`.
        """
        # Avoid float -> Decimal binary noise by going through ``str``.
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            raise InvalidOperationError(f"Amount is not a valid number: {amount!r}")

        if value.is_nan():
            raise InvalidOperationError("Amount must be a real number, not NaN")
        if value <= 0:
            raise InvalidOperationError("Amount must be positive")

        return value.quantize(_MONEY_QUANT)

    def _ensure_operational(self) -> None:
        """Raise if the account's status forbids transactions."""
        if self._status is AccountStatus.FROZEN:
            raise AccountFrozenError(
                f"Account {self._account_id} is frozen and cannot transact"
            )
        if self._status is AccountStatus.CLOSED:
            raise AccountClosedError(
                f"Account {self._account_id} is closed and cannot transact"
            )

    # --- Operations to be implemented by concrete types -------------------------------

    @abstractmethod
    def deposit(self, amount) -> Decimal:
        """Add ``amount`` to the balance; return the new balance."""

    @abstractmethod
    def withdraw(self, amount) -> Decimal:
        """Remove ``amount`` from the balance; return the new balance."""

    @abstractmethod
    def get_account_info(self) -> dict:
        """Return a serializable snapshot of the account's state."""


class BankAccount(AbstractAccount):
    """A standard bank account with validation and status-aware operations."""

    def __init__(
        self,
        owner: str,
        *,
        account_id: str | None = None,
        balance=0,
        status: AccountStatus = AccountStatus.ACTIVE,
        currency: Currency = Currency.RUB,
    ) -> None:
        if not isinstance(owner, str) or not owner.strip():
            raise InvalidOperationError("Owner must be a non-empty string")
        if not isinstance(status, AccountStatus):
            raise InvalidOperationError("status must be an AccountStatus")
        if not isinstance(currency, Currency):
            raise InvalidOperationError("currency must be a Currency")

        initial = self._validate_initial_balance(balance)
        # Generate a short, human-friendly id when none is supplied.
        resolved_id = account_id if account_id else uuid.uuid4().hex[:8].upper()

        super().__init__(
            owner=owner.strip(),
            account_id=str(resolved_id),
            balance=initial,
            status=status,
            currency=currency,
        )

    @staticmethod
    def _validate_initial_balance(balance) -> Decimal:
        try:
            value = Decimal(str(balance))
        except (InvalidOperation, ValueError, TypeError):
            raise InvalidOperationError(f"Initial balance is not a number: {balance!r}")
        if value.is_nan() or value < 0:
            raise InvalidOperationError("Initial balance must be non-negative")
        return value.quantize(_MONEY_QUANT)

    def deposit(self, amount) -> Decimal:
        self._ensure_operational()
        value = self._validate_amount(amount)
        self._balance += value
        return self._balance

    def withdraw(self, amount) -> Decimal:
        self._ensure_operational()
        value = self._validate_amount(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                f"Cannot withdraw {value}; balance is {self._balance}"
            )
        self._balance -= value
        return self._balance

    def get_account_info(self) -> dict:
        return {
            "account_id": self._account_id,
            "owner": self._owner,
            "status": self._status.value,
            "balance": self._balance,
            "currency": self._currency.value,
        }

    def __str__(self) -> str:
        last4 = self._account_id[-4:]
        return (
            f"{type(self).__name__} | {self._owner} | ****{last4} | "
            f"{self._status.value.upper()} | {self._balance} {self._currency.value}"
        )
