"""Unit tests for the Client and Bank classes."""

from datetime import datetime
from decimal import Decimal

import pytest

from src.domain import (
    AccountFrozenError,
    AccountStatus,
    Bank,
    Client,
    ClientBlockedError,
    ClientNotFoundError,
    Currency,
    InvalidOperationError,
    NightOperationError,
    UnderageError,
)


def make_client(**kwargs):
    defaults = dict(full_name="Alice Smith", age=30, pin="1234")
    defaults.update(kwargs)
    return Client(**defaults)


# A clock fixed at midday so the night-window rule never interferes by default.
def midday():
    return datetime(2026, 6, 9, 12, 0, 0)


def night():
    return datetime(2026, 6, 9, 2, 0, 0)


# --- Client ---------------------------------------------------------------------------

def test_client_requires_minimum_age():
    with pytest.raises(UnderageError):
        make_client(age=17)


def test_client_auto_id_and_defaults():
    c = make_client()
    assert len(c.client_id) == 8
    assert not c.is_blocked
    assert c.account_numbers == []


def test_client_pin_is_not_stored_plaintext():
    c = make_client(pin="1234")
    info = c.get_client_info()
    assert "1234" not in str(info)
    assert c.verify_pin("1234") and not c.verify_pin("0000")


# --- Bank: clients & accounts ---------------------------------------------------------

def test_add_client_and_duplicate_rejected():
    bank = Bank(now=midday)
    c = bank.add_client(make_client(client_id="C1"))
    assert bank.clients == [c]
    with pytest.raises(InvalidOperationError):
        bank.add_client(make_client(client_id="C1"))


def test_open_account_links_to_client():
    bank = Bank(now=midday)
    bank.add_client(make_client(client_id="C1"))
    acc = bank.open_account("C1", "savings", balance=1000, min_balance=100)
    assert acc.account_id in bank.clients[0].account_numbers
    assert acc.balance == Decimal("1000.00")


def test_open_account_unknown_client():
    bank = Bank(now=midday)
    with pytest.raises(ClientNotFoundError):
        bank.open_account("nope")


def test_open_account_unknown_type():
    bank = Bank(now=midday)
    bank.add_client(make_client(client_id="C1"))
    with pytest.raises(InvalidOperationError):
        bank.open_account("C1", "crypto")


def test_freeze_unfreeze_close():
    bank = Bank(now=midday)
    bank.add_client(make_client(client_id="C1"))
    acc = bank.open_account("C1", "bank", balance=100)

    bank.freeze_account(acc.account_id)
    assert acc.status is AccountStatus.FROZEN
    with pytest.raises(AccountFrozenError):
        acc.withdraw(10)

    bank.unfreeze_account(acc.account_id)
    assert acc.status is AccountStatus.ACTIVE

    bank.close_account(acc.account_id)
    assert acc.status is AccountStatus.CLOSED


# --- Bank: security -------------------------------------------------------------------

def test_authenticate_success_resets_attempts():
    bank = Bank(now=midday)
    c = bank.add_client(make_client(client_id="C1", pin="1234"))
    bank.authenticate_client("C1", "0000")  # one failure
    assert c.failed_attempts == 1
    assert bank.authenticate_client("C1", "1234") is True
    assert c.failed_attempts == 0


def test_three_bad_logins_block_client():
    bank = Bank(now=midday)
    c = bank.add_client(make_client(client_id="C1", pin="1234"))
    for _ in range(3):
        assert bank.authenticate_client("C1", "0000") is False
    assert c.is_blocked
    assert c.suspicious_flags  # at least one suspicious mark recorded
    with pytest.raises(ClientBlockedError):
        bank.authenticate_client("C1", "1234")


def test_night_window_blocks_operations():
    bank = Bank(now=night)
    bank.add_client(make_client(client_id="C1"))
    with pytest.raises(NightOperationError):
        bank.open_account("C1", "bank", balance=100)


def test_daytime_allows_operations():
    bank = Bank(now=midday)
    bank.add_client(make_client(client_id="C1"))
    acc = bank.open_account("C1", "bank", balance=100)
    assert acc.balance == Decimal("100.00")


# --- Bank: search & analytics ---------------------------------------------------------

def build_populated_bank():
    bank = Bank(now=midday)
    bank.add_client(make_client(client_id="C1", full_name="Alice"))
    bank.add_client(make_client(client_id="C2", full_name="Bob"))
    bank.open_account("C1", "bank", balance=1000, currency=Currency.USD)
    bank.open_account("C1", "savings", balance=500, currency=Currency.USD, min_balance=0)
    bank.open_account("C2", "bank", balance=300, currency=Currency.EUR)
    return bank


def test_search_accounts_filters():
    bank = build_populated_bank()
    usd = bank.search_accounts(currency=Currency.USD)
    assert len(usd) == 2
    rich = bank.search_accounts(min_balance=600)
    assert all(a.balance >= Decimal("600") for a in rich)
    owned = bank.search_accounts(owner="Bob")
    assert len(owned) == 1


def test_get_total_balance_per_currency():
    bank = build_populated_bank()
    totals = bank.get_total_balance()
    assert totals["USD"] == Decimal("1500.00")
    assert totals["EUR"] == Decimal("300.00")
    assert bank.get_total_balance(currency=Currency.EUR) == Decimal("300.00")


def test_clients_ranking_order():
    bank = build_populated_bank()
    ranking = bank.get_clients_ranking()
    assert [row["full_name"] for row in ranking] == ["Alice", "Bob"]
    assert ranking[0]["total"] == Decimal("1500.00")
