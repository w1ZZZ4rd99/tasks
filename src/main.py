"""Demonstration of the bank account model.

Run with::

    python -m src.main
"""

from .errors import DomainError
from .models import AccountStatus, BankAccount, Currency


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


if __name__ == "__main__":
    main()
