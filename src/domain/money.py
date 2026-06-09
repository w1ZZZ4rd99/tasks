"""Money helpers shared across the domain.

Monetary values use :class:`decimal.Decimal` for correct money arithmetic (binary floats
cannot represent values like ``0.10`` exactly).
"""

from decimal import Decimal, InvalidOperation

from .errors import InvalidOperationError

# Two decimal places is enough for the currencies we support.
MONEY_QUANT = Decimal("0.01")


def quantize_money(value: Decimal) -> Decimal:
    """Round a Decimal to the standard money precision."""
    return value.quantize(MONEY_QUANT)


def parse_amount(amount) -> Decimal:
    """Parse and validate a strictly positive operation amount.

    Returns the amount as a money-quantized ``Decimal``. Rejects non-numeric input, NaN,
    zero, and negative values with :class:`InvalidOperationError`.
    """
    # Going through ``str`` avoids float -> Decimal binary noise.
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise InvalidOperationError(f"Amount is not a valid number: {amount!r}")
    if value.is_nan():
        raise InvalidOperationError("Amount must be a real number, not NaN")
    if value <= 0:
        raise InvalidOperationError("Amount must be positive")
    return quantize_money(value)


def decimal_nonneg(value, field: str) -> Decimal:
    """Parse ``value`` into a non-negative Decimal or raise.

    Not money-quantized: also used for rates that need more than two decimal places.
    """
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise InvalidOperationError(f"{field} is not a number: {value!r}")
    if result.is_nan() or result < 0:
        raise InvalidOperationError(f"{field} must be non-negative")
    return result
