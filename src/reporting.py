"""Reporting and visualization: text/JSON/CSV reports and matplotlib charts.

Run with::

    python -m src.reporting
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from decimal import Decimal
from enum import Enum

import matplotlib

matplotlib.use("Agg")  # headless: render charts to files without a display
import matplotlib.pyplot as plt  # noqa: E402 - must follow backend selection

from .domain import (
    AuditReporter,
    RiskLevel,
    TransactionStatus,
    client_transactions,
    transaction_statistics,
)

# Generated artifacts go into a tmp/ folder inside the repo (portable across OSes,
# unlike the system temp directory which does not exist on Windows).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(_REPO_ROOT, "tmp")


def _json_safe(value):
    """Convert report values into JSON-serializable forms."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _cell(value) -> str:
    """Stringify a value for a CSV cell."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (list, dict)):
        return json.dumps(_json_safe(value))
    return "" if value is None else str(value)


class ReportBuilder:
    """Builds reports and charts from a bank and its transaction processor."""

    def __init__(self, bank, processor) -> None:
        self._bank = bank
        self._processor = processor
        self._audit = AuditReporter(processor.audit)

    # --- Report data (serializable dicts) ----------------------------------------------

    def client_report(self, client_id: str) -> dict:
        client = self._bank.get_client(client_id)
        accounts = [self._account_row(self._bank.get_account(n))
                    for n in client.account_numbers]
        history = client_transactions(self._bank, client_id, self._processor.history)
        return {
            "type": "client",
            "client": client.get_client_info(),
            "accounts": accounts,
            "transactions": [tx.to_dict() for tx in history],
            "risk_profile": self._audit.client_risk_profile(self._bank, client_id),
        }

    def bank_report(self) -> dict:
        return {
            "type": "bank",
            "bank": {
                "name": self._bank.name,
                "clients": len(self._bank.clients),
                "accounts": len(self._bank.accounts),
            },
            "total_balance": self._bank.get_total_balance(),
            "ranking": self._bank.get_clients_ranking(),
            "transaction_statistics": transaction_statistics(self._processor.history),
            "accounts": [self._account_row(a) for a in self._bank.accounts],
        }

    def risk_report(self) -> dict:
        risk_levels = {level.name: 0 for level in RiskLevel}
        for event in self._processor.audit.filter(action="risk.assessed"):
            level = event.metadata.get("risk_level")
            name = level.name if isinstance(level, RiskLevel) else level
            if name in risk_levels:
                risk_levels[name] += 1
        return {
            "type": "risk",
            "suspicious_operations": [e.to_dict() for e in self._audit.suspicious_operations()],
            "error_statistics": self._audit.error_statistics(),
            "risk_levels": risk_levels,
        }

    @staticmethod
    def _account_row(account) -> dict:
        return {
            "account_id": account.account_id,
            "owner": account.owner,
            "type": type(account).__name__,
            "balance": account.balance,
            "currency": account.currency.value,
            "status": account.status.value,
        }

    # --- Rendering / export ------------------------------------------------------------

    def to_text(self, report: dict) -> str:
        title = f"{report.get('type', 'report').upper()} REPORT"
        lines = [title, "=" * len(title)]
        _render(report, lines, indent=0)
        return "\n".join(lines)

    def export_to_json(self, data, path: str) -> str:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_json_safe(data), fh, indent=2)
        return path

    def export_to_csv(self, rows, path: str) -> str:
        rows = list(rows)
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: _cell(row.get(k)) for k in fieldnames})
        return path

    # --- Charts ------------------------------------------------------------------------

    def chart_currency_pie(self):
        """Pie chart of total balance per currency."""
        totals = self._bank.get_total_balance()
        labels = list(totals.keys())
        values = [float(totals[k]) for k in labels]
        fig, ax = plt.subplots()
        ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90)
        ax.set_title("Total balance by currency")
        return fig

    def chart_transactions_bar(self):
        """Bar chart of transaction counts by type."""
        by_type = transaction_statistics(self._processor.history)["by_type"]
        labels = list(by_type.keys())
        values = [by_type[k] for k in labels]
        fig, ax = plt.subplots()
        ax.bar(labels, values, color="steelblue")
        ax.set_title("Transactions by type")
        ax.set_ylabel("count")
        fig.autofmt_xdate(rotation=30)
        return fig

    def chart_balance_movement(self, account_id: str):
        """Line chart of cumulative net flow for an account over its transactions.

        Net flow only (cross-currency conversion is not applied), used to visualize activity.
        """
        running = Decimal("0.00")
        points = [0.0]
        for tx in self._processor.history:
            if tx.status is not TransactionStatus.COMPLETED:
                continue
            if tx.receiver == account_id:
                running += tx.amount
            elif tx.sender == account_id:
                running -= tx.amount + tx.fee
            else:
                continue
            points.append(float(running))
        fig, ax = plt.subplots()
        ax.plot(range(len(points)), points, marker="o")
        ax.set_title(f"Net flow — account {account_id}")
        ax.set_xlabel("operation #")
        ax.set_ylabel("cumulative net flow")
        return fig

    def save_charts(self, output_dir: str, account_id: str | None = None) -> list[str]:
        """Save the three charts as PNGs into ``output_dir``; return the file paths."""
        os.makedirs(output_dir, exist_ok=True)
        if account_id is None and self._bank.accounts:
            account_id = self._bank.accounts[0].account_id

        figures = {
            "currency_pie.png": self.chart_currency_pie(),
            "transactions_bar.png": self.chart_transactions_bar(),
            "balance_movement.png": self.chart_balance_movement(account_id),
        }
        paths = []
        for name, fig in figures.items():
            path = os.path.join(output_dir, name)
            fig.savefig(path)
            plt.close(fig)
            paths.append(path)
        return paths


def _render(value, lines: list[str], indent: int) -> None:
    """Recursively render a report value into indented text lines."""
    pad = "  " * indent
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(val, (dict, list)):
                lines.append(f"{pad}{key}:")
                _render(val, lines, indent + 1)
            else:
                lines.append(f"{pad}{key}: {val}")
    elif isinstance(value, list):
        if not value:
            lines.append(f"{pad}(none)")
        for item in value:
            if isinstance(item, (dict, list)):
                _render(item, lines, indent)
                lines.append(f"{pad}-")
            else:
                lines.append(f"{pad}- {item}")
    else:
        lines.append(f"{pad}{value}")


def _demo() -> None:
    from . import simulation

    result = simulation.simulate()
    bank, processor = result["bank"], result["processor"]
    builder = ReportBuilder(bank, processor)

    for report in (builder.bank_report(), builder.client_report("C1"), builder.risk_report()):
        print(builder.to_text(report))
        print()

    os.makedirs(TMP_DIR, exist_ok=True)
    json_path = builder.export_to_json(builder.bank_report(),
                                       os.path.join(TMP_DIR, "bank.json"))
    csv_path = builder.export_to_csv(builder.bank_report()["accounts"],
                                     os.path.join(TMP_DIR, "accounts.csv"))
    charts = builder.save_charts(TMP_DIR)
    print("Exports written:")
    for path in [json_path, csv_path, *charts]:
        print(f"  {path}")


if __name__ == "__main__":
    _demo()
