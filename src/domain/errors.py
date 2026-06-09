"""Domain error hierarchy for the banking system.

A single ``DomainError`` base lets callers catch any domain-level failure with one
``except`` clause, while specific subclasses allow fine-grained handling.
"""


class DomainError(Exception):
    """Base class for all domain (business-rule) errors."""


class InvalidOperationError(DomainError):
    """Raised when an operation receives invalid input (e.g. a bad amount)."""


class InsufficientFundsError(DomainError):
    """Raised when a withdrawal exceeds the available balance."""


class AccountFrozenError(DomainError):
    """Raised when an operation is attempted on a frozen account."""


class AccountClosedError(DomainError):
    """Raised when an operation is attempted on a closed account."""


class UnderageError(DomainError):
    """Raised when a client is younger than the minimum allowed age."""


class ClientBlockedError(DomainError):
    """Raised when a blocked client attempts to authenticate or operate."""


class NightOperationError(DomainError):
    """Raised when an operation is attempted during the nightly lockout window."""


class TransactionError(DomainError):
    """Raised when a transaction cannot be executed under the business rules."""


class UnknownCurrencyRateError(DomainError):
    """Raised when no exchange rate is available for a currency."""


class EntityNotFoundError(DomainError):
    """Base for lookups that fail to find a registered entity."""


class ClientNotFoundError(EntityNotFoundError):
    """Raised when no client matches a given id."""


class AccountNotFoundError(EntityNotFoundError):
    """Raised when no account matches a given id."""
