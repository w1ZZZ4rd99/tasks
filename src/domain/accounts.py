"""Bank account models.

An abstract account base encapsulates shared state and validation; concrete types
(``BankAccount`` and its subclasses) implement operations with their own rules.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from decimal import Decimal

from .enums import ANNUAL_RETURNS, AccountStatus, AssetClass, Currency
from .errors import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)
from .money import decimal_nonneg, parse_amount, quantize_money


class AbstractAccount(ABC):
    """Abstract base for every account type.

    Holds the state shared by all accounts (id, owner, balance, status, currency). Subclasses
    implement the actual operations so different account types can apply their own rules
    (overdraft, interest, fees, ...).
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

    def set_status(self, status: AccountStatus) -> None:
        """Update the account status (used by the managing Bank)."""
        if not isinstance(status, AccountStatus):
            raise InvalidOperationError("status must be an AccountStatus")
        self._status = status

    # --- Shared validation reused by subclasses ---------------------------------------

    def _validate_amount(self, amount) -> Decimal:
        """Validate and normalize a strictly positive operation amount."""
        return parse_amount(amount)

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

        initial = quantize_money(decimal_nonneg(balance, "Initial balance"))
        # Generate a short, human-friendly id when none is supplied.
        resolved_id = account_id if account_id else uuid.uuid4().hex[:8].upper()

        super().__init__(
            owner=owner.strip(),
            account_id=str(resolved_id),
            balance=initial,
            status=status,
            currency=currency,
        )

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


class SavingsAccount(BankAccount):
    """Interest-bearing account that must keep a minimum balance."""

    def __init__(self, owner: str, *, min_balance=0, monthly_rate=0, **kwargs) -> None:
        super().__init__(owner, **kwargs)
        self._min_balance = quantize_money(decimal_nonneg(min_balance, "min_balance"))
        self._monthly_rate = decimal_nonneg(monthly_rate, "monthly_rate")

    @property
    def min_balance(self) -> Decimal:
        return self._min_balance

    @property
    def monthly_rate(self) -> Decimal:
        return self._monthly_rate

    def withdraw(self, amount) -> Decimal:
        """Withdraw, but never let the balance drop below ``min_balance``."""
        self._ensure_operational()
        value = self._validate_amount(amount)
        if self._balance - value < self._min_balance:
            raise InsufficientFundsError(
                f"Withdrawal would breach the minimum balance of {self._min_balance}; "
                f"available above minimum is {self._balance - self._min_balance}"
            )
        self._balance -= value
        return self._balance

    def apply_monthly_interest(self) -> Decimal:
        """Credit one month of interest on the current balance; return the amount added."""
        interest = quantize_money(self._balance * self._monthly_rate)
        self._balance += interest
        return interest

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update(
            type="savings",
            min_balance=self._min_balance,
            monthly_rate=self._monthly_rate,
        )
        return info

    def __str__(self) -> str:
        return f"{super().__str__()} | min={self._min_balance}, rate={self._monthly_rate}"


class PremiumAccount(BankAccount):
    """Account with higher withdrawal limits, overdraft, and a fixed per-withdrawal fee."""

    def __init__(
        self,
        owner: str,
        *,
        overdraft_limit=0,
        withdrawal_limit=1_000_000,
        transaction_fee=0,
        **kwargs,
    ) -> None:
        super().__init__(owner, **kwargs)
        self._overdraft_limit = quantize_money(
            decimal_nonneg(overdraft_limit, "overdraft_limit")
        )
        self._withdrawal_limit = quantize_money(
            decimal_nonneg(withdrawal_limit, "withdrawal_limit")
        )
        self._transaction_fee = quantize_money(
            decimal_nonneg(transaction_fee, "transaction_fee")
        )

    @property
    def overdraft_limit(self) -> Decimal:
        return self._overdraft_limit

    @property
    def withdrawal_limit(self) -> Decimal:
        return self._withdrawal_limit

    @property
    def transaction_fee(self) -> Decimal:
        return self._transaction_fee

    def withdraw(self, amount) -> Decimal:
        """Withdraw with a fixed fee; the balance may go negative down to the overdraft limit."""
        self._ensure_operational()
        value = self._validate_amount(amount)
        if value > self._withdrawal_limit:
            raise InvalidOperationError(
                f"Amount {value} exceeds the withdrawal limit of {self._withdrawal_limit}"
            )
        total = value + self._transaction_fee
        if self._balance - total < -self._overdraft_limit:
            raise InsufficientFundsError(
                f"Withdrawal of {value} plus fee {self._transaction_fee} exceeds the "
                f"overdraft limit; balance is {self._balance}"
            )
        self._balance -= total
        return self._balance

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update(
            type="premium",
            overdraft_limit=self._overdraft_limit,
            withdrawal_limit=self._withdrawal_limit,
            transaction_fee=self._transaction_fee,
        )
        return info

    def __str__(self) -> str:
        return (
            f"{super().__str__()} | overdraft={self._overdraft_limit}, "
            f"fee={self._transaction_fee}"
        )


class InvestmentAccount(BankAccount):
    """Account holding a cash balance plus a portfolio of virtual assets."""

    def __init__(self, owner: str, *, portfolio=None, **kwargs) -> None:
        super().__init__(owner, **kwargs)
        # Portfolio maps each asset class to its current market value (cash is separate).
        self._portfolio = {asset: Decimal("0.00") for asset in AssetClass}
        for asset, value in (portfolio or {}).items():
            self._portfolio[self._coerce_asset(asset)] = quantize_money(
                decimal_nonneg(value, "portfolio value")
            )

    @staticmethod
    def _coerce_asset(asset) -> AssetClass:
        if isinstance(asset, AssetClass):
            return asset
        try:
            return AssetClass(str(asset).lower())
        except ValueError:
            raise InvalidOperationError(f"Unknown asset class: {asset!r}")

    @property
    def portfolio(self) -> dict:
        return dict(self._portfolio)

    def portfolio_value(self) -> Decimal:
        """Total market value of all holdings."""
        return sum(self._portfolio.values(), Decimal("0.00"))

    def invest(self, asset, amount) -> Decimal:
        """Move cash from the balance into an asset class; return that holding's new value."""
        self._ensure_operational()
        value = self._validate_amount(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                f"Cannot invest {value}; cash balance is {self._balance}"
            )
        key = self._coerce_asset(asset)
        self._balance -= value
        self._portfolio[key] += value
        return self._portfolio[key]

    def project_yearly_growth(self) -> Decimal:
        """Projected one-year growth across the portfolio using assumed annual returns."""
        growth = sum(
            (value * ANNUAL_RETURNS[asset] for asset, value in self._portfolio.items()),
            Decimal("0"),
        )
        return quantize_money(growth)

    def withdraw(self, amount) -> Decimal:
        """Withdraw from the cash balance only; invested holdings are not liquid."""
        self._ensure_operational()
        value = self._validate_amount(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                f"Cannot withdraw {value}; liquid cash balance is {self._balance} "
                f"(invested {self.portfolio_value()} is not withdrawable)"
            )
        self._balance -= value
        return self._balance

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info.update(
            type="investment",
            portfolio={a.value: v for a, v in self._portfolio.items()},
            portfolio_value=self.portfolio_value(),
            projected_yearly_growth=self.project_yearly_growth(),
        )
        return info

    def __str__(self) -> str:
        return (
            f"{super().__str__()} | portfolio={self.portfolio_value()} "
            f"{self._currency.value}"
        )
