"""Comprehensive end-to-end simulation of the banking system.

Run with::

    python -m src.simulation
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from .domain import (
    AccountStatus,
    AuditReporter,
    Bank,
    Client,
    Currency,
    RiskAnalyzer,
    Transaction,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
    client_transactions,
    transaction_statistics,
)

DEFAULT_SEED = 7
MIDDAY = datetime(2026, 6, 9, 12, 0, 0)

CLIENT_NAMES = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace"]
ACCOUNT_TYPE_CYCLE = ["bank", "savings", "premium", "investment"]
CURRENCY_CYCLE = [Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT, Currency.CNY]


def build_bank(rng: random.Random):
    """Create a bank with 7 clients and 12 accounts; freeze one account."""
    bank = Bank("Mega Bank", now=lambda: MIDDAY)
    clients = [
        bank.add_client(Client(name, rng.randint(20, 60), pin=f"pin{i}", client_id=f"C{i}"))
        for i, name in enumerate(CLIENT_NAMES, 1)
    ]

    accounts = []
    for i in range(12):
        client = clients[i % len(clients)]
        acc_type = ACCOUNT_TYPE_CYCLE[i % len(ACCOUNT_TYPE_CYCLE)]
        currency = CURRENCY_CYCLE[i % len(CURRENCY_CYCLE)]
        kwargs = {"balance": rng.randint(5000, 20000), "currency": currency}
        if acc_type == "savings":
            kwargs.update(min_balance=100, monthly_rate="0.03")
        elif acc_type == "premium":
            kwargs.update(overdraft_limit=2000, transaction_fee=5)
        accounts.append(bank.open_account(client.client_id, acc_type, **kwargs))

    # Freeze one account so later operations against it are rejected.
    bank.freeze_account(accounts[3].account_id)
    return bank, accounts


def generate_transactions(rng: random.Random, accounts) -> list[Transaction]:
    """Build ~40 transactions: mostly normal, plus crafted erroneous and suspicious ones."""
    active = [a for a in accounts if a.status is AccountStatus.ACTIVE]
    txs: list[Transaction] = []

    # Normal traffic: weighted toward deposits/withdrawals, fewer transfers.
    for _ in range(34):
        roll = rng.random()
        if roll < 0.5:
            acc = rng.choice(accounts)
            txs.append(Transaction(TransactionType.DEPOSIT, rng.randint(50, 1000),
                                   acc.currency, receiver=acc.account_id))
        elif roll < 0.8:
            acc = rng.choice(active)
            txs.append(Transaction(TransactionType.WITHDRAWAL, rng.randint(50, 500),
                                   acc.currency, sender=acc.account_id))
        else:
            src, dst = rng.sample(active, 2)
            txs.append(Transaction(TransactionType.TRANSFER, rng.randint(50, 500),
                                   src.currency, sender=src.account_id,
                                   receiver=dst.account_id))

    # Erroneous transactions.
    txs.append(Transaction(TransactionType.WITHDRAWAL, 10_000_000, active[0].currency,
                           sender=active[0].account_id))  # overdraw
    frozen = accounts[3]
    txs.append(Transaction(TransactionType.WITHDRAWAL, 100, frozen.currency,
                           sender=frozen.account_id))  # frozen account
    txs.append(Transaction(TransactionType.TRANSFER, 100, active[1].currency,
                           sender=active[1].account_id, receiver="GHOST-404"))  # no such account

    # Suspicious transactions: large transfers to brand-new external accounts -> blocked.
    txs.append(Transaction(TransactionType.EXTERNAL_TRANSFER, 75000, active[2].currency,
                           sender=active[2].account_id, receiver="EXT-NEW-1"))
    txs.append(Transaction(TransactionType.EXTERNAL_TRANSFER, 90000, active[4].currency,
                           sender=active[4].account_id, receiver="EXT-NEW-2"))
    # Moderate transfer to a new external account -> flagged but executed.
    txs.append(Transaction(TransactionType.EXTERNAL_TRANSFER, 300, active[5].currency,
                           sender=active[5].account_id, receiver="EXT-NEW-3"))
    return txs


def simulate(seed: int = DEFAULT_SEED) -> dict:
    """Build the bank, run all transactions through the queue, and return the artifacts."""
    rng = random.Random(seed)
    bank, accounts = build_bank(rng)
    transactions = generate_transactions(rng, accounts)

    # Advancing clock so the frequency rule stays quiet for normally spaced traffic.
    state = {"t": MIDDAY}
    analyzer = RiskAnalyzer(large_amount=50000, frequency_limit=4)
    processor = TransactionProcessor(bank, risk=analyzer, now=lambda: state["t"])
    queue = TransactionQueue(now=lambda: MIDDAY)

    for tx in transactions:
        queue.add(tx)

    while True:
        tx = queue.dequeue_ready()
        if tx is None:
            break
        processor.process(tx)
        state["t"] += timedelta(minutes=2)

    return {
        "bank": bank,
        "accounts": accounts,
        "processor": processor,
        "transactions": transactions,
    }


def run(seed: int = DEFAULT_SEED) -> None:
    """Run the simulation and print initialization, processing, scenarios, and reports."""
    result = simulate(seed)
    bank, processor = result["bank"], result["processor"]
    accounts, transactions = result["accounts"], result["transactions"]

    print("=== Initialization ===")
    print(f"Bank: {bank.name} | clients: {len(bank.clients)} | accounts: {len(accounts)}")

    print(f"\n=== Simulation: {len(transactions)} transactions queued ===\n")
    for tx in processor.history:
        if tx.status is TransactionStatus.COMPLETED:
            print(f"  [OK]  {tx}")
        else:
            print(f"  [NO]  {tx} — {tx.failure_reason}")

    print("\n=== User scenarios (client C1) ===")
    client = bank.get_client("C1")
    print(f"Client: {client}")
    for number in client.account_numbers:
        print(f"  account {bank.get_account(number)}")
    history = client_transactions(bank, "C1", processor.history)
    print(f"Transaction history: {len(history)} operation(s)")
    suspicious = AuditReporter(processor.audit).suspicious_operations()
    print(f"Suspicious operations (bank-wide): {len(suspicious)}")

    print("\n=== Reports ===")
    print("Top-3 clients by balance:")
    for row in bank.get_clients_ranking()[:3]:
        print(f"  {row['full_name']}: {row['total']}")
    stats = transaction_statistics(processor.history)
    print(f"Transaction statistics: {stats}")
    print(f"Total balance per currency: {bank.get_total_balance()}")


if __name__ == "__main__":
    run()
