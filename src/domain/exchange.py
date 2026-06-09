"""Currency exchange rates and conversion."""

from __future__ import annotations

from decimal import Decimal

from .enums import Currency
from .errors import UnknownCurrencyRateError
from .money import quantize_money

# Value of one unit of each currency expressed in USD. Conversion goes via USD.
DEFAULT_RATES = {
    Currency.USD: Decimal("1"),
    Currency.EUR: Decimal("1.08"),
    Currency.RUB: Decimal("0.011"),
    Currency.KZT: Decimal("0.0021"),
    Currency.CNY: Decimal("0.14"),
}


class ExchangeRates:
    """Converts amounts between currencies using USD as the pivot."""

    def __init__(self, rates: dict | None = None) -> None:
        self._rates = dict(rates) if rates else dict(DEFAULT_RATES)

    def _rate(self, currency: Currency) -> Decimal:
        try:
            return self._rates[currency]
        except KeyError:
            raise UnknownCurrencyRateError(f"No exchange rate for {currency}")

    def convert(self, amount: Decimal, frm: Currency, to: Currency) -> Decimal:
        """Convert ``amount`` from one currency to another, money-quantized."""
        if frm is to:
            return quantize_money(Decimal(amount))
        in_usd = Decimal(amount) * self._rate(frm)
        return quantize_money(in_usd / self._rate(to))
