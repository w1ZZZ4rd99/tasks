"""Unit tests for the account model."""

from decimal import Decimal

import pytest

from src.errors import (
    AccountClosedError,
    AccountFrozenError,
    InsufficientFundsError,
    InvalidOperationError,
)
from src.models import AccountStatus, BankAccount, Currency


def test_auto_generates_short_id_when_missing():
    acc = BankAccount("Alice")
    assert isinstance(acc.account_id, str)
    assert len(acc.account_id) == 8


def test_uses_provided_account_id():
    acc = BankAccount("Alice", account_id="ACC-12345678")
    assert acc.account_id == "ACC-12345678"


def test_defaults():
    acc = BankAccount("Alice")
    assert acc.status is AccountStatus.ACTIVE
    assert acc.currency is Currency.RUB
    assert acc.balance == Decimal("0.00")


def test_deposit_increases_balance():
    acc = BankAccount("Alice", balance=100)
    assert acc.deposit(50) == Decimal("150.00")
    assert acc.balance == Decimal("150.00")


def test_withdraw_decreases_balance():
    acc = BankAccount("Alice", balance=100)
    assert acc.withdraw(40) == Decimal("60.00")
    assert acc.balance == Decimal("60.00")


@pytest.mark.parametrize("bad", [0, -1, -0.01, "abc", None, float("nan")])
def test_invalid_amount_rejected(bad):
    acc = BankAccount("Alice", balance=100)
    with pytest.raises(InvalidOperationError):
        acc.deposit(bad)


def test_overdraw_raises():
    acc = BankAccount("Alice", balance=30)
    with pytest.raises(InsufficientFundsError):
        acc.withdraw(31)
    # Balance unchanged after a failed withdrawal.
    assert acc.balance == Decimal("30.00")


def test_frozen_account_blocks_operations():
    acc = BankAccount("Bob", balance=100, status=AccountStatus.FROZEN)
    with pytest.raises(AccountFrozenError):
        acc.deposit(10)
    with pytest.raises(AccountFrozenError):
        acc.withdraw(10)


def test_closed_account_blocks_operations():
    acc = BankAccount("Bob", balance=100, status=AccountStatus.CLOSED)
    with pytest.raises(AccountClosedError):
        acc.deposit(10)
    with pytest.raises(AccountClosedError):
        acc.withdraw(10)


def test_negative_initial_balance_rejected():
    with pytest.raises(InvalidOperationError):
        BankAccount("Alice", balance=-5)


def test_empty_owner_rejected():
    with pytest.raises(InvalidOperationError):
        BankAccount("   ")


def test_str_masks_all_but_last4():
    acc = BankAccount("Alice", account_id="ABCD1234", balance=10, currency=Currency.USD)
    assert str(acc) == "BankAccount | Alice | ****1234 | ACTIVE | 10.00 USD"


def test_get_account_info_contents():
    acc = BankAccount("Alice", account_id="ABCD1234", balance=10, currency=Currency.EUR)
    info = acc.get_account_info()
    assert info == {
        "account_id": "ABCD1234",
        "owner": "Alice",
        "status": "active",
        "balance": Decimal("10.00"),
        "currency": "EUR",
    }


def test_decimal_precision_no_float_noise():
    acc = BankAccount("Alice", balance=0)
    acc.deposit(0.1)
    acc.deposit(0.2)
    assert acc.balance == Decimal("0.30")
