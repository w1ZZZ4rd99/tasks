"""Unit tests for the advanced account types."""

from decimal import Decimal

import pytest

from src.domain import (
    AccountFrozenError,
    AccountStatus,
    AssetClass,
    InsufficientFundsError,
    InvalidOperationError,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
)


# --- SavingsAccount -------------------------------------------------------------------

def test_savings_apply_monthly_interest():
    acc = SavingsAccount("Carol", balance=1000, monthly_rate="0.05")
    assert acc.apply_monthly_interest() == Decimal("50.00")
    assert acc.balance == Decimal("1050.00")


def test_savings_withdraw_respects_min_balance():
    acc = SavingsAccount("Carol", balance=1000, min_balance=200)
    assert acc.withdraw(800) == Decimal("200.00")
    with pytest.raises(InsufficientFundsError):
        acc.withdraw(1)  # would drop below the minimum


def test_savings_info_and_str():
    acc = SavingsAccount(
        "Carol", account_id="ABCD1234", balance=500, min_balance=100, monthly_rate="0.03"
    )
    info = acc.get_account_info()
    assert info["type"] == "savings"
    assert info["min_balance"] == Decimal("100.00")
    assert "min=" in str(acc) and "rate=" in str(acc)


# --- PremiumAccount -------------------------------------------------------------------

def test_premium_overdraft_and_fee():
    acc = PremiumAccount("Dave", balance=100, overdraft_limit=500, transaction_fee=5)
    # 400 + 5 fee = 405 deducted -> balance -305, within -500 overdraft.
    assert acc.withdraw(400) == Decimal("-305.00")


def test_premium_overdraft_limit_enforced():
    acc = PremiumAccount("Dave", balance=0, overdraft_limit=100, transaction_fee=0)
    with pytest.raises(InsufficientFundsError):
        acc.withdraw(101)


def test_premium_withdrawal_limit_enforced():
    acc = PremiumAccount("Dave", balance=10000, withdrawal_limit=1000)
    with pytest.raises(InvalidOperationError):
        acc.withdraw(1001)


def test_premium_info():
    acc = PremiumAccount("Dave", balance=100, overdraft_limit=500, transaction_fee=5)
    info = acc.get_account_info()
    assert info["type"] == "premium"
    assert info["overdraft_limit"] == Decimal("500.00")
    assert info["transaction_fee"] == Decimal("5.00")


# --- InvestmentAccount ----------------------------------------------------------------

def test_investment_invest_moves_cash_to_portfolio():
    acc = InvestmentAccount("Eve", balance=1000)
    assert acc.invest(AssetClass.STOCKS, 400) == Decimal("400.00")
    assert acc.balance == Decimal("600.00")
    assert acc.portfolio_value() == Decimal("400.00")


def test_investment_invest_rejects_over_balance():
    acc = InvestmentAccount("Eve", balance=100)
    with pytest.raises(InsufficientFundsError):
        acc.invest(AssetClass.BONDS, 200)


def test_investment_unknown_asset_rejected():
    with pytest.raises(InvalidOperationError):
        InvestmentAccount("Eve", balance=100, portfolio={"crypto": 50})


def test_investment_project_yearly_growth():
    acc = InvestmentAccount("Eve", portfolio={"stocks": 1000, "bonds": 1000, "etf": 1000})
    # 1000*0.10 + 1000*0.04 + 1000*0.07 = 210
    assert acc.project_yearly_growth() == Decimal("210.00")


def test_investment_withdraw_only_touches_cash():
    acc = InvestmentAccount("Eve", balance=500, portfolio={"stocks": 1000})
    assert acc.withdraw(500) == Decimal("0.00")
    with pytest.raises(InsufficientFundsError):
        acc.withdraw(1)  # invested funds are not liquid


def test_investment_info_and_str():
    acc = InvestmentAccount("Eve", balance=100, portfolio={"etf": 500})
    info = acc.get_account_info()
    assert info["type"] == "investment"
    assert info["portfolio"]["etf"] == Decimal("500.00")
    assert "portfolio=" in str(acc)


# --- Polymorphism ---------------------------------------------------------------------

def test_polymorphic_withdraw_and_info():
    accounts = [
        SavingsAccount("A", balance=1000, min_balance=100),
        PremiumAccount("B", balance=1000, transaction_fee=2),
        InvestmentAccount("C", balance=1000),
    ]
    for acc in accounts:
        acc.withdraw(10)  # each type's own withdraw runs without error
        assert "type" in acc.get_account_info()


def test_inherited_status_checks_still_apply():
    acc = SavingsAccount("A", balance=1000, status=AccountStatus.FROZEN)
    with pytest.raises(AccountFrozenError):
        acc.withdraw(10)
