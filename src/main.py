"""Demonstration of the bank account model.

Run with::

    python -m src.main
"""

from .errors import DomainError
from .models import (
    AccountStatus,
    AssetClass,
    BankAccount,
    Currency,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
)


def main() -> None:
    print("=== Bank account model ===\n")

    # 1. Create an active account and a frozen account.
    active = BankAccount("Alice", balance=1000, currency=Currency.USD)
    frozen = BankAccount(
        "Bob", balance=500, status=AccountStatus.FROZEN, currency=Currency.EUR
    )
    print("Created accounts:")
    print(f"  {active}")
    print(f"  {frozen}\n")

    # 2. Operations on the frozen account are rejected.
    print("Attempting operations on the frozen account:")
    for label, op in (("deposit", lambda: frozen.deposit(100)),
                      ("withdraw", lambda: frozen.withdraw(100))):
        try:
            op()
        except DomainError as exc:
            print(f"  {label} blocked -> {type(exc).__name__}: {exc}")
    print()

    # 3. Valid deposit and withdrawal on the active account.
    print("Valid operations on the active account:")
    active.deposit(250)
    print(f"  after deposit(250):  balance = {active.balance} {active.currency.value}")
    active.withdraw(400)
    print(f"  after withdraw(400): balance = {active.balance} {active.currency.value}")
    print(f"\nFinal state: {active}")
    print(f"Info dict:   {active.get_account_info()}")

    demo_account_types()


def demo_account_types() -> None:
    print("\n=== Advanced account types ===\n")

    # SavingsAccount: minimum balance + monthly interest.
    savings = SavingsAccount(
        "Carol", balance=1000, min_balance=200, monthly_rate="0.05", currency=Currency.RUB
    )
    print(savings)
    interest = savings.apply_monthly_interest()
    print(f"  monthly interest credited: {interest} -> balance {savings.balance}")
    try:
        savings.withdraw(950)  # would drop below min_balance
    except DomainError as exc:
        print(f"  withdraw(950) blocked -> {type(exc).__name__}: {exc}")
    print(f"  withdraw(300) ok -> balance {savings.withdraw(300)}\n")

    # PremiumAccount: overdraft + fixed fee.
    premium = PremiumAccount(
        "Dave", balance=100, overdraft_limit=500, transaction_fee=5, currency=Currency.USD
    )
    print(premium)
    print(f"  withdraw(400) with overdraft -> balance {premium.withdraw(400)} (fee applied)\n")

    # InvestmentAccount: portfolio of virtual assets + growth projection.
    invest = InvestmentAccount("Eve", balance=10000, currency=Currency.EUR)
    invest.invest(AssetClass.STOCKS, 4000)
    invest.invest(AssetClass.BONDS, 3000)
    invest.invest(AssetClass.ETF, 2000)
    print(invest)
    holdings = {asset.value: str(value) for asset, value in invest.portfolio.items()}
    print(f"  portfolio: {holdings}")
    print(f"  projected yearly growth: {invest.project_yearly_growth()} {invest.currency.value}")


if __name__ == "__main__":
    main()
