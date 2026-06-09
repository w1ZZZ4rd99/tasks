"""Domain error hierarchy for the banking system.

A single ``DomainError`` base lets callers catch any domain-level failure with one
``except`` clause, while specific subclasses allow fine-grained handling. The hierarchy is
intended to grow in later days (transactions, audit, reporting) without breaking callers.
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
