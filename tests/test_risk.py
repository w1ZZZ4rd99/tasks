"""Unit tests for risk analysis and its integration with the processor."""

from datetime import datetime, timedelta
from decimal import Decimal

from src.domain import (
    AuditLog,
    AuditReporter,
    Bank,
    Client,
    Currency,
    RiskAnalyzer,
    RiskLevel,
    Transaction,
    TransactionProcessor,
    TransactionStatus,
    TransactionType,
)


def midday():
    return datetime(2026, 6, 9, 12, 0, 0)


def night():
    return datetime(2026, 6, 9, 2, 0, 0)


def deposit(amount=10, **kwargs):
    return Transaction(TransactionType.DEPOSIT, amount, Currency.USD, **kwargs)


def transfer(amount=10, sender="A", receiver="B", **kwargs):
    return Transaction(TransactionType.TRANSFER, amount, Currency.USD,
                       sender=sender, receiver=receiver, **kwargs)


# --- Individual rules -----------------------------------------------------------------

def test_normal_transaction_is_low_risk():
    analyzer = RiskAnalyzer()
    assessment = analyzer.assess(deposit(50), midday())
    assert assessment.level is RiskLevel.LOW
    assert assessment.reasons == []


def test_large_amount_flagged():
    analyzer = RiskAnalyzer(large_amount=1000)
    assessment = analyzer.assess(deposit(5000), midday())
    assert assessment.level is RiskLevel.MEDIUM
    assert any("large amount" in r for r in assessment.reasons)


def test_night_operation_flagged():
    analyzer = RiskAnalyzer()
    assessment = analyzer.assess(deposit(10), night())
    assert any("night" in r for r in assessment.reasons)


def test_transfer_to_new_account_flagged_then_known():
    analyzer = RiskAnalyzer()
    first = analyzer.assess(transfer(sender="A", receiver="NEW"), midday())
    assert any("new account" in r for r in first.reasons)
    # Same receiver is now known, so the new-account rule no longer fires.
    second = analyzer.assess(transfer(sender="A", receiver="NEW"), midday())
    assert not any("new account" in r for r in second.reasons)


def test_frequent_operations_flagged():
    analyzer = RiskAnalyzer(frequency_limit=3, frequency_window=timedelta(seconds=60))
    now = midday()
    analyzer.assess(transfer(sender="A", receiver="A"), now)
    analyzer.assess(transfer(sender="A", receiver="A"), now)
    third = analyzer.assess(transfer(sender="A", receiver="A"), now)
    assert any("frequent" in r for r in third.reasons)


def test_high_risk_from_combined_rules():
    analyzer = RiskAnalyzer(large_amount=1000)
    # large (+2) at night (+1) = score 3 -> HIGH
    assessment = analyzer.assess(deposit(5000), night())
    assert assessment.level is RiskLevel.HIGH


# --- Processor integration ------------------------------------------------------------

def build_bank():
    bank = Bank(now=midday)
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    usd = bank.open_account("C1", "bank", balance=100000, currency=Currency.USD)
    return bank, usd


def test_processor_blocks_high_risk_and_leaves_balance_untouched():
    bank, usd = build_bank()
    analyzer = RiskAnalyzer(large_amount=1000)
    proc = TransactionProcessor(bank, risk=analyzer, now=night)

    tx = Transaction(TransactionType.WITHDRAWAL, 5000, Currency.USD, sender=usd.account_id)
    assert proc.process(tx) is False
    assert tx.status is TransactionStatus.FAILED
    assert "blocked by risk analysis" in tx.failure_reason
    assert usd.balance == Decimal("100000.00")  # never executed
    assert proc.audit.filter(action="transaction.blocked")


def test_processor_uses_provided_empty_audit_log(tmp_path):
    # Regression: an empty AuditLog is falsy via __len__, so `audit or ...` would discard it.
    bank, usd = build_bank()
    path = tmp_path / "audit.jsonl"
    audit = AuditLog(file_path=str(path), now=midday)
    proc = TransactionProcessor(bank, audit=audit, now=midday)
    assert proc.audit is audit

    proc.process(Transaction(TransactionType.DEPOSIT, 10, Currency.USD, receiver=usd.account_id))
    assert len(audit) >= 1
    assert path.exists()  # streamed to the file


def test_processor_allows_normal_transaction():
    bank, usd = build_bank()
    analyzer = RiskAnalyzer(large_amount=1000)
    proc = TransactionProcessor(bank, risk=analyzer, now=midday)

    tx = Transaction(TransactionType.WITHDRAWAL, 100, Currency.USD, sender=usd.account_id)
    assert proc.process(tx) is True
    assert usd.balance == Decimal("99900.00")
    assert proc.audit.filter(action="transaction.completed")


# --- Reports over a mixed set of transactions -----------------------------------------

def test_reports_over_normal_and_suspicious_transactions():
    bank = Bank(now=midday)
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    usd = bank.open_account("C1", "bank", balance=100000, currency=Currency.USD)
    # High frequency limit so only the amount/new-account rules drive this scenario.
    analyzer = RiskAnalyzer(large_amount=1000, frequency_limit=10)
    proc = TransactionProcessor(bank, risk=analyzer, now=midday)

    txs = [
        Transaction(TransactionType.WITHDRAWAL, 50, Currency.USD, sender=usd.account_id),
        Transaction(TransactionType.WITHDRAWAL, 80, Currency.USD, sender=usd.account_id),
        # HIGH risk: large amount (+2) to a new external account (+1) -> blocked.
        Transaction(TransactionType.EXTERNAL_TRANSFER, 9000, Currency.USD,
                    sender=usd.account_id, receiver="EXT-NEW"),
        # MEDIUM risk (large only): executes, then fails on insufficient funds.
        Transaction(TransactionType.WITHDRAWAL, 999999, Currency.USD, sender=usd.account_id),
    ]
    for tx in txs:
        proc.process(tx)

    reporter = AuditReporter(proc.audit)

    assert len(reporter.suspicious_operations()) >= 1

    profile = reporter.client_risk_profile(bank, "C1")
    assert profile["client_id"] == "C1"
    assert profile["assessed_operations"] == 4
    assert profile["highest_level"] == "HIGH"

    stats = reporter.error_statistics()
    assert stats["by_type"].get("RiskBlocked") == 1
    assert "InsufficientFundsError" in stats["by_type"]
