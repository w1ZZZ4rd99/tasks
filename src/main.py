"""Demonstration of the bank account model.

Run with::

    python -m src.main
"""

from .domain import (
    AccountStatus,
    AssetClass,
    Bank,
    BankAccount,
    Client,
    Currency,
    DomainError,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
    Transaction,
    TransactionPriority,
    TransactionProcessor,
    TransactionQueue,
    TransactionType,
    UnderageError,
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

    demo_bank()


def demo_bank() -> None:
    print("\n=== Bank system ===\n")
    bank = Bank("Demo Bank")

    # Underage clients are rejected.
    try:
        Client("Young Tom", 16, pin="0000")
    except UnderageError as exc:
        print(f"Underage client rejected -> {exc}")

    alice = bank.add_client(Client("Alice Smith", 30, pin="1234", client_id="ALICE001"))
    bob = bank.add_client(Client("Bob Jones", 45, pin="4321", client_id="BOB002"))

    # Open accounts of different types.
    a1 = bank.open_account(alice.client_id, "savings", balance=5000, min_balance=500,
                           monthly_rate="0.04", currency=Currency.USD)
    bank.open_account(alice.client_id, "premium", balance=2000, overdraft_limit=1000,
                      transaction_fee=10, currency=Currency.USD)
    bank.open_account(bob.client_id, "investment", balance=8000, currency=Currency.EUR)
    print(f"{alice} | accounts: {alice.account_numbers}")
    print(f"{bob} | accounts: {bob.account_numbers}\n")

    # Freeze an account and show operations are blocked.
    bank.freeze_account(a1.account_id)
    print(f"Froze {a1.account_id}; status now {a1.status.value}")
    try:
        a1.withdraw(100)
    except DomainError as exc:
        print(f"  withdraw blocked -> {type(exc).__name__}: {exc}\n")
    bank.unfreeze_account(a1.account_id)

    # Authentication: correct pin, then three wrong pins -> blocked.
    print(f"Authenticate Alice (correct pin): {bank.authenticate_client('ALICE001', '1234')}")
    for _ in range(3):
        bank.authenticate_client("BOB002", "0000")
    print(f"Bob blocked after 3 bad logins: {bob.is_blocked}")
    print(f"Bob suspicious flags: {bob.suspicious_flags}")
    try:
        bank.authenticate_client("BOB002", "4321")
    except DomainError as exc:
        print(f"  further auth blocked -> {type(exc).__name__}: {exc}\n")

    # Search and analytics.
    usd_accounts = bank.search_accounts(currency=Currency.USD)
    print(f"USD accounts: {[a.account_id for a in usd_accounts]}")
    print(f"Total balance per currency: {bank.get_total_balance()}")
    print(f"Clients ranking: {bank.get_clients_ranking()}")

    demo_transactions()


def demo_transactions() -> None:
    print("\n=== Transaction system ===\n")
    bank = Bank("Demo Bank")
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    bank.add_client(Client("Bob", 30, pin="2", client_id="C2"))
    usd = bank.open_account("C1", "bank", balance=1000, currency=Currency.USD)
    eur = bank.open_account("C2", "bank", balance=1000, currency=Currency.EUR)

    processor = TransactionProcessor(bank)
    queue = TransactionQueue()

    transactions = [
        Transaction(TransactionType.DEPOSIT, 200, Currency.USD, receiver=usd.account_id),
        Transaction(TransactionType.WITHDRAWAL, 150, Currency.USD, sender=usd.account_id),
        Transaction(TransactionType.TRANSFER, 100, Currency.USD,
                    sender=usd.account_id, receiver=eur.account_id),
        Transaction(TransactionType.EXTERNAL_TRANSFER, 100, Currency.USD,
                    sender=usd.account_id, receiver="EXT-OUT"),
        Transaction(TransactionType.WITHDRAWAL, 999999, Currency.USD, sender=usd.account_id),
        Transaction(TransactionType.DEPOSIT, 25, Currency.USD, receiver=usd.account_id,
                    priority=TransactionPriority.HIGH),
        Transaction(TransactionType.DEPOSIT, 10, Currency.EUR, receiver=eur.account_id,
                    priority=TransactionPriority.LOW),
        Transaction(TransactionType.DEPOSIT, 5, Currency.USD, receiver=usd.account_id,
                    transaction_id="CANCELLED-1"),
        Transaction(TransactionType.DEPOSIT, 3, Currency.USD, receiver=usd.account_id),
        Transaction(TransactionType.WITHDRAWAL, 50, Currency.EUR, sender=eur.account_id),
    ]
    for tx in transactions:
        queue.add(tx)
    queue.cancel("CANCELLED-1")

    print(f"Queued {len(queue)} transactions; processing in priority order...\n")
    processed = processor.process_queue(queue)
    for tx in processed:
        line = f"  {tx}"
        if tx.failure_reason:
            line += f"  (reason: {tx.failure_reason})"
        print(line)

    print(f"\nFinal balances: USD {usd.balance}, EUR {eur.balance}")
    print(f"Errors logged: {len(processor.error_log)}")


if __name__ == "__main__":
    main()
