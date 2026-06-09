"""Tests for the Day 6 helpers and the end-to-end simulation."""

from datetime import datetime
from decimal import Decimal

from src.domain import (
    Bank,
    Client,
    Currency,
    Transaction,
    TransactionStatus,
    TransactionType,
    client_transactions,
    transaction_statistics,
)
from src.simulation import simulate, run


def midday():
    return datetime(2026, 6, 9, 12, 0, 0)


# --- transaction_statistics -----------------------------------------------------------

def test_transaction_statistics_counts_and_volume():
    completed = Transaction(TransactionType.DEPOSIT, 100, Currency.USD)
    completed.mark_completed(midday())
    failed = Transaction(TransactionType.WITHDRAWAL, 50, Currency.USD)
    failed.mark_failed("nope", midday())
    pending = Transaction(TransactionType.DEPOSIT, 25, Currency.USD)

    stats = transaction_statistics([completed, failed, pending])
    assert stats["total"] == 3
    assert stats["by_status"]["COMPLETED"] == 1
    assert stats["by_status"]["FAILED"] == 1
    assert stats["by_status"]["PENDING"] == 1
    assert stats["by_type"]["deposit"] == 2
    assert stats["total_volume"] == Decimal("100.00")  # only completed amounts
    assert stats["success_rate"] == round(1 / 3, 4)


def test_transaction_statistics_empty():
    stats = transaction_statistics([])
    assert stats["total"] == 0
    assert stats["success_rate"] == 0.0


# --- client_transactions --------------------------------------------------------------

def test_client_transactions_filters_by_owned_accounts():
    bank = Bank(now=midday)
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    bank.add_client(Client("Bob", 30, pin="2", client_id="C2"))
    a = bank.open_account("C1", "bank", balance=100)
    b = bank.open_account("C2", "bank", balance=100)

    txs = [
        Transaction(TransactionType.WITHDRAWAL, 10, Currency.RUB, sender=a.account_id),
        Transaction(TransactionType.DEPOSIT, 10, Currency.RUB, receiver=b.account_id),
        Transaction(TransactionType.TRANSFER, 10, Currency.RUB,
                    sender=b.account_id, receiver=a.account_id),
    ]
    owned = client_transactions(bank, "C1", txs)
    # First (sender a) and third (receiver a) involve C1; the second does not.
    assert owned == [txs[0], txs[2]]


# --- End-to-end simulation ------------------------------------------------------------

def test_simulation_history_and_consistency():
    result = simulate(seed=7)
    proc = result["processor"]
    txs = result["transactions"]

    # Every generated transaction was processed and recorded.
    assert len(proc.history) == len(txs)

    stats = transaction_statistics(proc.history)
    counts = stats["by_status"]
    assert (counts["COMPLETED"] + counts["FAILED"]
            + counts["CANCELLED"] + counts["PENDING"]) == len(txs)
    # The crafted erroneous + suspicious transactions guarantee failures and blocks.
    assert counts["FAILED"] >= 1
    assert proc.audit.filter(action="transaction.blocked")


def test_run_prints_all_sections(capsys):
    run(seed=7)
    out = capsys.readouterr().out
    for marker in ("Initialization", "Simulation", "User scenarios", "Reports",
                   "Total balance"):
        assert marker in out
