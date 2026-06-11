"""Tests for the reporting and visualization layer."""

import json
from datetime import datetime
from decimal import Decimal

from matplotlib.figure import Figure

from src.domain import (
    Bank,
    Client,
    Currency,
    Transaction,
    TransactionProcessor,
    TransactionType,
)
from src.reporting import ReportBuilder


def midday():
    return datetime(2026, 6, 9, 12, 0, 0)


def build():
    bank = Bank("Test Bank", now=midday)
    bank.add_client(Client("Alice", 30, pin="1", client_id="C1"))
    bank.add_client(Client("Bob", 30, pin="2", client_id="C2"))
    usd = bank.open_account("C1", "bank", balance=1000, currency=Currency.USD)
    eur = bank.open_account("C2", "bank", balance=500, currency=Currency.EUR)

    proc = TransactionProcessor(bank, now=midday)
    proc.process(Transaction(TransactionType.DEPOSIT, 200, Currency.USD, receiver=usd.account_id))
    proc.process(Transaction(TransactionType.WITHDRAWAL, 100, Currency.USD, sender=usd.account_id))
    proc.process(Transaction(TransactionType.WITHDRAWAL, 99999, Currency.USD,
                             sender=usd.account_id))  # fails
    return bank, proc, usd, eur


# --- Reports --------------------------------------------------------------------------

def test_bank_report_structure():
    bank, proc, usd, eur = build()
    report = ReportBuilder(bank, proc).bank_report()
    assert report["type"] == "bank"
    assert report["bank"]["clients"] == 2
    assert report["total_balance"]["USD"] == usd.balance
    assert report["transaction_statistics"]["total"] == 3
    assert len(report["accounts"]) == 2


def test_client_report_structure():
    bank, proc, usd, _ = build()
    report = ReportBuilder(bank, proc).client_report("C1")
    assert report["client"]["client_id"] == "C1"
    assert len(report["accounts"]) == 1
    # All three transactions involve C1's USD account.
    assert len(report["transactions"]) == 3
    assert "risk_profile" in report


def test_risk_report_structure():
    bank, proc, _, _ = build()
    report = ReportBuilder(bank, proc).risk_report()
    assert set(report["risk_levels"]) == {"LOW", "MEDIUM", "HIGH"}
    assert "error_statistics" in report
    assert "suspicious_operations" in report


# --- Export ---------------------------------------------------------------------------

def test_export_to_json(tmp_path):
    bank, proc, _, _ = build()
    builder = ReportBuilder(bank, proc)
    path = builder.export_to_json(builder.bank_report(), str(tmp_path / "bank.json"))
    data = json.loads((tmp_path / "bank.json").read_text(encoding="utf-8"))
    assert data["type"] == "bank"
    assert data["total_balance"]["USD"] == "1100.00"  # Decimal serialized as string
    assert path.endswith("bank.json")


def test_export_to_csv(tmp_path):
    bank, proc, _, _ = build()
    builder = ReportBuilder(bank, proc)
    rows = builder.bank_report()["accounts"]
    builder.export_to_csv(rows, str(tmp_path / "accounts.csv"))
    lines = (tmp_path / "accounts.csv").read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].split(",")[0] == "account_id"  # header
    assert len(lines) == 1 + len(rows)


def test_to_text_contains_title():
    bank, proc, _, _ = build()
    text = ReportBuilder(bank, proc).to_text(ReportBuilder(bank, proc).bank_report())
    assert "BANK REPORT" in text
    assert "total_balance" in text


# --- Charts ---------------------------------------------------------------------------

def test_chart_methods_return_figures():
    bank, proc, usd, _ = build()
    builder = ReportBuilder(bank, proc)
    assert isinstance(builder.chart_currency_pie(), Figure)
    assert isinstance(builder.chart_transactions_bar(), Figure)
    assert isinstance(builder.chart_balance_movement(usd.account_id), Figure)


def test_save_charts_writes_three_pngs(tmp_path):
    bank, proc, usd, _ = build()
    paths = ReportBuilder(bank, proc).save_charts(str(tmp_path), account_id=usd.account_id)
    assert len(paths) == 3
    for path in paths:
        assert path.endswith(".png")
        with open(path, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"  # PNG magic number
