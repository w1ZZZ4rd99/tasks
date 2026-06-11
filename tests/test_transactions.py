"""Unit tests for the transaction system."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from src.domain import (
    Bank,
    Client,
    Currency,
    ExchangeRates,
    FeePolicy,
    Transaction,
    TransactionPriority,
    TransactionProcessor,
    TransactionQueue,
    TransactionStatus,
    TransactionType,
    UnknownCurrencyRateError,
)


def midday():
    return datetime(2026, 6, 9, 12, 0, 0)


def make_bank_with_accounts():
    bank = Bank(now=midday)
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    bank.add_client(Client("Bob", 30, pin="2", client_id="C2"))
    usd = bank.open_account("C1", "bank", balance=1000, currency=Currency.USD)
    eur = bank.open_account("C2", "bank", balance=1000, currency=Currency.EUR)
    return bank, usd, eur


# --- ExchangeRates --------------------------------------------------------------------

def test_convert_same_currency_is_noop():
    rates = ExchangeRates()
    assert rates.convert(Decimal("100"), Currency.USD, Currency.USD) == Decimal("100.00")


def test_convert_cross_currency():
    rates = ExchangeRates({Currency.USD: Decimal("1"), Currency.EUR: Decimal("2")})
    # 100 EUR -> 200 USD
    assert rates.convert(Decimal("100"), Currency.EUR, Currency.USD) == Decimal("200.00")


def test_convert_unknown_rate_raises():
    rates = ExchangeRates({Currency.USD: Decimal("1")})
    with pytest.raises(UnknownCurrencyRateError):
        rates.convert(Decimal("100"), Currency.EUR, Currency.USD)


# --- Transaction ----------------------------------------------------------------------

def test_transaction_defaults_and_validation():
    tx = Transaction(TransactionType.DEPOSIT, 100, Currency.USD, receiver="A")
    assert tx.status is TransactionStatus.PENDING
    assert tx.amount == Decimal("100.00")
    assert tx.fee == Decimal("0.00")


def test_transaction_is_ready_respects_schedule():
    future = midday() + timedelta(hours=1)
    tx = Transaction(TransactionType.DEPOSIT, 10, Currency.USD, scheduled_at=future)
    assert not tx.is_ready(midday())
    assert tx.is_ready(future)


def test_transaction_status_transitions():
    tx = Transaction(TransactionType.DEPOSIT, 10, Currency.USD)
    tx.mark_failed("nope", midday())
    assert tx.status is TransactionStatus.FAILED and tx.failure_reason == "nope"


# --- TransactionQueue -----------------------------------------------------------------

def test_queue_serves_by_priority():
    q = TransactionQueue(now=midday)
    low = Transaction(TransactionType.DEPOSIT, 1, Currency.USD, priority=TransactionPriority.LOW)
    high = Transaction(TransactionType.DEPOSIT, 1, Currency.USD, priority=TransactionPriority.HIGH)
    q.add(low)
    q.add(high)
    assert q.dequeue_ready() is high
    assert q.dequeue_ready() is low


def test_queue_skips_deferred():
    q = TransactionQueue(now=midday)
    future = midday() + timedelta(hours=2)
    deferred = Transaction(TransactionType.DEPOSIT, 1, Currency.USD, scheduled_at=future)
    q.add(deferred)
    assert q.dequeue_ready() is None  # not ready yet


def test_queue_cancel():
    q = TransactionQueue(now=midday)
    tx = Transaction(TransactionType.DEPOSIT, 1, Currency.USD, transaction_id="T1")
    q.add(tx)
    assert q.cancel("T1") is True
    assert tx.status is TransactionStatus.CANCELLED
    assert len(q) == 0


# --- FeePolicy ------------------------------------------------------------------------

def test_fee_policy_external_only():
    fees = FeePolicy(external_rate=Decimal("0.02"))
    assert fees.fee_for(TransactionType.EXTERNAL_TRANSFER, Decimal("100")) == Decimal("2.00")
    assert fees.fee_for(TransactionType.TRANSFER, Decimal("100")) == Decimal("0.00")


# --- TransactionProcessor -------------------------------------------------------------

def test_process_deposit_and_withdrawal():
    bank, usd, _ = make_bank_with_accounts()
    proc = TransactionProcessor(bank, now=midday)

    dep = Transaction(TransactionType.DEPOSIT, 200, Currency.USD, receiver=usd.account_id)
    assert proc.process(dep) is True
    assert usd.balance == Decimal("1200.00")

    wd = Transaction(TransactionType.WITHDRAWAL, 300, Currency.USD, sender=usd.account_id)
    assert proc.process(wd) is True
    assert usd.balance == Decimal("900.00")


def test_process_internal_transfer_with_conversion():
    bank, usd, eur = make_bank_with_accounts()
    rates = ExchangeRates({Currency.USD: Decimal("1"), Currency.EUR: Decimal("2")})
    proc = TransactionProcessor(bank, exchange=rates, now=midday)

    tx = Transaction(
        TransactionType.TRANSFER, 100, Currency.USD,
        sender=usd.account_id, receiver=eur.account_id,
    )
    assert proc.process(tx) is True
    assert usd.balance == Decimal("900.00")
    # 100 USD -> 50 EUR at the given rates.
    assert eur.balance == Decimal("1050.00")


def test_process_external_transfer_charges_fee():
    bank, usd, _ = make_bank_with_accounts()
    proc = TransactionProcessor(bank, fees=FeePolicy(external_rate=Decimal("0.01")), now=midday)

    tx = Transaction(
        TransactionType.EXTERNAL_TRANSFER, 100, Currency.USD,
        sender=usd.account_id, receiver="EXT-XYZ",
    )
    assert proc.process(tx) is True
    assert tx.fee == Decimal("1.00")
    assert usd.balance == Decimal("899.00")  # 100 + 1 fee


def test_insufficient_funds_fails_without_retry():
    bank, usd, _ = make_bank_with_accounts()
    proc = TransactionProcessor(bank, max_retries=3, now=midday)

    tx = Transaction(TransactionType.WITHDRAWAL, 99999, Currency.USD, sender=usd.account_id)
    assert proc.process(tx) is False
    assert tx.status is TransactionStatus.FAILED
    assert tx.attempts == 1  # business-rule failure: no retry


def test_frozen_account_fails():
    bank, usd, _ = make_bank_with_accounts()
    bank.freeze_account(usd.account_id)
    proc = TransactionProcessor(bank, now=midday)

    tx = Transaction(TransactionType.WITHDRAWAL, 10, Currency.USD, sender=usd.account_id)
    assert proc.process(tx) is False
    assert tx.status is TransactionStatus.FAILED


def test_premium_can_transfer_into_overdraft():
    bank = Bank(now=midday)
    bank.add_client(Client("Pam", 30, pin="1", client_id="P1"))
    bank.add_client(Client("Quinn", 30, pin="2", client_id="P2"))
    premium = bank.open_account("P1", "premium", balance=100, overdraft_limit=1000,
                                currency=Currency.USD)
    dest = bank.open_account("P2", "bank", balance=0, currency=Currency.USD)
    proc = TransactionProcessor(bank, now=midday)

    tx = Transaction(TransactionType.TRANSFER, 500, Currency.USD,
                     sender=premium.account_id, receiver=dest.account_id)
    assert proc.process(tx) is True
    assert premium.balance < 0  # overdraft used


def test_transfer_to_frozen_account_rolls_back_sender():
    bank, usd, eur = make_bank_with_accounts()
    bank.freeze_account(eur.account_id)
    proc = TransactionProcessor(bank, now=midday)

    tx = Transaction(TransactionType.TRANSFER, 100, Currency.USD,
                     sender=usd.account_id, receiver=eur.account_id)
    assert proc.process(tx) is False
    assert tx.status is TransactionStatus.FAILED
    # Atomicity: the debited amount is restored, nothing was credited.
    assert usd.balance == Decimal("1000.00")
    assert eur.balance == Decimal("1000.00")


def test_transfer_rollback_restores_premium_fee():
    bank = Bank(now=midday)
    bank.add_client(Client("Pam", 30, pin="1", client_id="P1"))
    bank.add_client(Client("Quinn", 30, pin="2", client_id="P2"))
    premium = bank.open_account("P1", "premium", balance=1000, transaction_fee=5,
                                currency=Currency.USD)
    dest = bank.open_account("P2", "bank", balance=0, currency=Currency.USD)
    bank.freeze_account(dest.account_id)
    proc = TransactionProcessor(bank, now=midday)

    tx = Transaction(TransactionType.TRANSFER, 100, Currency.USD,
                     sender=premium.account_id, receiver=dest.account_id)
    assert proc.process(tx) is False
    # The rollback also returns the premium per-withdrawal fee.
    assert premium.balance == Decimal("1000.00")


def test_deposit_and_withdrawal_convert_transaction_currency():
    bank, usd, eur = make_bank_with_accounts()
    rates = ExchangeRates({Currency.USD: Decimal("1"), Currency.EUR: Decimal("2")})
    proc = TransactionProcessor(bank, exchange=rates, now=midday)

    dep = Transaction(TransactionType.DEPOSIT, 100, Currency.USD, receiver=eur.account_id)
    assert proc.process(dep) is True
    assert eur.balance == Decimal("1050.00")  # 100 USD -> 50 EUR

    wd = Transaction(TransactionType.WITHDRAWAL, 50, Currency.EUR, sender=usd.account_id)
    assert proc.process(wd) is True
    assert usd.balance == Decimal("900.00")  # 50 EUR -> 100 USD


def test_transfer_converts_from_transaction_currency():
    bank, usd, eur = make_bank_with_accounts()
    rates = ExchangeRates({Currency.USD: Decimal("1"), Currency.EUR: Decimal("2")})
    proc = TransactionProcessor(bank, exchange=rates, now=midday)

    tx = Transaction(TransactionType.TRANSFER, 50, Currency.EUR,
                     sender=usd.account_id, receiver=eur.account_id)
    assert proc.process(tx) is True
    assert usd.balance == Decimal("900.00")  # 50 EUR cost 100 USD
    assert eur.balance == Decimal("1050.00")  # credited as-is in EUR


def test_external_transfer_converts_amount_and_fee():
    bank, _, eur = make_bank_with_accounts()
    rates = ExchangeRates({Currency.USD: Decimal("1"), Currency.EUR: Decimal("2")})
    proc = TransactionProcessor(bank, exchange=rates,
                                fees=FeePolicy(external_rate=Decimal("0.01")), now=midday)

    tx = Transaction(TransactionType.EXTERNAL_TRANSFER, 100, Currency.USD,
                     sender=eur.account_id, receiver="EXT-XYZ")
    assert proc.process(tx) is True
    assert tx.fee == Decimal("1.00")  # in the transaction currency (USD)
    assert eur.balance == Decimal("949.50")  # 101 USD -> 50.50 EUR


def test_night_window_blocks_money_operations():
    clock = {"now": midday()}
    bank = Bank(now=lambda: clock["now"])
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    account = bank.open_account("C1", "bank", balance=1000, currency=Currency.USD)
    proc = TransactionProcessor(bank, now=lambda: clock["now"])

    clock["now"] = datetime(2026, 6, 9, 2, 0, 0)
    tx = Transaction(TransactionType.WITHDRAWAL, 10, Currency.USD, sender=account.account_id)
    assert proc.process(tx) is False
    assert tx.status is TransactionStatus.FAILED
    assert tx.attempts == 1  # business-rule failure: no retry
    assert account.balance == Decimal("1000.00")
    assert proc.error_log[0]["error_type"] == "NightOperationError"


def test_transient_error_is_retried_then_failed_and_logged():
    bank, usd, _ = make_bank_with_accounts()
    proc = TransactionProcessor(bank, max_retries=2, now=midday)

    # Force an unexpected (non-domain) error by pointing at a missing account object.
    class Boom:
        def deposit(self, amount):
            raise RuntimeError("transient glitch")

    bank._accounts["BOOM"] = Boom()
    tx = Transaction(TransactionType.DEPOSIT, 10, Currency.USD, receiver="BOOM")
    assert proc.process(tx) is False
    assert tx.attempts == 3  # initial + 2 retries
    assert len(proc.error_log) == 3


# --- End-to-end: 10 transactions through the queue ------------------------------------

def test_ten_transactions_through_queue():
    bank, usd, eur = make_bank_with_accounts()
    rates = ExchangeRates({Currency.USD: Decimal("1"), Currency.EUR: Decimal("1")})
    proc = TransactionProcessor(bank, exchange=rates, now=midday)
    q = TransactionQueue(now=midday)

    txs = [
        Transaction(TransactionType.DEPOSIT, 100, Currency.USD, receiver=usd.account_id),
        Transaction(TransactionType.DEPOSIT, 50, Currency.EUR, receiver=eur.account_id),
        Transaction(TransactionType.WITHDRAWAL, 200, Currency.USD, sender=usd.account_id),
        Transaction(TransactionType.TRANSFER, 100, Currency.USD,
                    sender=usd.account_id, receiver=eur.account_id),
        Transaction(TransactionType.EXTERNAL_TRANSFER, 100, Currency.USD,
                    sender=usd.account_id, receiver="EXT-1"),
        Transaction(TransactionType.WITHDRAWAL, 999999, Currency.USD, sender=usd.account_id),
        Transaction(TransactionType.DEPOSIT, 10, Currency.USD, receiver=usd.account_id,
                    priority=TransactionPriority.HIGH),
        Transaction(TransactionType.DEPOSIT, 5, Currency.EUR, receiver=eur.account_id,
                    priority=TransactionPriority.LOW),
        Transaction(TransactionType.DEPOSIT, 1, Currency.USD, receiver=usd.account_id,
                    scheduled_at=midday() + timedelta(hours=5)),  # deferred, stays pending
        Transaction(TransactionType.DEPOSIT, 7, Currency.USD, receiver=usd.account_id,
                    transaction_id="CANCEL-ME"),
    ]
    for tx in txs:
        q.add(tx)
    q.cancel("CANCEL-ME")

    processed = proc.process_queue(q)

    statuses = [tx.status for tx in processed]
    assert statuses.count(TransactionStatus.COMPLETED) == 7
    assert statuses.count(TransactionStatus.FAILED) == 1
    # The deferred transaction was never dequeued; the cancelled one is gone.
    assert len(q.pending) == 1
    assert txs[-1].status is TransactionStatus.CANCELLED
