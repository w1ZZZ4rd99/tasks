"""Enumerations and shared constants used across the domain."""

from decimal import Decimal
from enum import Enum


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


class ClientStatus(Enum):
    """Lifecycle status of a client."""

    ACTIVE = "active"
    BLOCKED = "blocked"


class AssetClass(Enum):
    """Virtual asset classes an investment portfolio may hold."""

    STOCKS = "stocks"
    BONDS = "bonds"
    ETF = "etf"


class TransactionType(Enum):
    """Kinds of transactions the processor can execute."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"  # internal, between two of the bank's accounts
    EXTERNAL_TRANSFER = "external_transfer"  # money leaving the bank


class TransactionStatus(Enum):
    """Lifecycle status of a transaction."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TransactionPriority(Enum):
    """Queue priority; higher value is served first."""

    LOW = 1
    NORMAL = 2
    HIGH = 3


# Assumed annual return rate per asset class, used for growth projections.
ANNUAL_RETURNS = {
    AssetClass.STOCKS: Decimal("0.10"),
    AssetClass.BONDS: Decimal("0.04"),
    AssetClass.ETF: Decimal("0.07"),
}
