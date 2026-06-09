"""The managing Bank aggregate: clients, accounts, and security policies."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Callable

from .accounts import (
    AbstractAccount,
    BankAccount,
    InvestmentAccount,
    PremiumAccount,
    SavingsAccount,
)
from .client import Client
from .enums import AccountStatus, Currency
from .errors import (
    AccountNotFoundError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    NightOperationError,
)

# Maps an account-type key to its class for open_account().
ACCOUNT_TYPES = {
    "bank": BankAccount,
    "savings": SavingsAccount,
    "premium": PremiumAccount,
    "investment": InvestmentAccount,
}

# Nightly lockout window: operations are forbidden in [NIGHT_START, NIGHT_END).
NIGHT_START = 0
NIGHT_END = 5


class Bank:
    """Central registry of clients and accounts with authentication and safety rules."""

    def __init__(self, name: str = "Bank", *, now: Callable[[], datetime] = datetime.now):
        self._name = name
        self._clients: dict[str, Client] = {}
        self._accounts: dict[str, AbstractAccount] = {}
        # Injectable clock keeps the night-window rule unit-testable.
        self._now = now

    @property
    def name(self) -> str:
        return self._name

    @property
    def clients(self) -> list[Client]:
        return list(self._clients.values())

    @property
    def accounts(self) -> list[AbstractAccount]:
        return list(self._accounts.values())

    # --- Clients -----------------------------------------------------------------------

    def add_client(self, client: Client) -> Client:
        if client.client_id in self._clients:
            raise InvalidOperationError(f"Client {client.client_id} already exists")
        self._clients[client.client_id] = client
        return client

    def get_client(self, client_id: str) -> Client:
        try:
            return self._clients[client_id]
        except KeyError:
            raise ClientNotFoundError(f"No client with id {client_id!r}")

    def get_account(self, account_id: str) -> AbstractAccount:
        try:
            return self._accounts[account_id]
        except KeyError:
            raise AccountNotFoundError(f"No account with id {account_id!r}")

    def find_client_by_account(self, account_id: str) -> Client | None:
        """Return the client owning the given account, or None."""
        for client in self._clients.values():
            if account_id in client.account_numbers:
                return client
        return None

    # Backwards-compatible internal aliases.
    _get_client = get_client
    _get_account = get_account

    # --- Accounts ----------------------------------------------------------------------

    def open_account(
        self, client_id: str, account_type: str = "bank", **kwargs
    ) -> AbstractAccount:
        """Open an account of ``account_type`` for a client and link it to them."""
        self._ensure_business_hours()
        client = self._get_client(client_id)
        try:
            account_cls = ACCOUNT_TYPES[account_type]
        except KeyError:
            raise InvalidOperationError(f"Unknown account type: {account_type!r}")

        account = account_cls(owner=client.full_name, **kwargs)
        self._accounts[account.account_id] = account
        client.add_account_number(account.account_id)
        return account

    def close_account(self, account_id: str) -> None:
        self._ensure_business_hours()
        self._get_account(account_id).set_status(AccountStatus.CLOSED)

    def freeze_account(self, account_id: str) -> None:
        self._ensure_business_hours()
        self._get_account(account_id).set_status(AccountStatus.FROZEN)

    def unfreeze_account(self, account_id: str) -> None:
        self._ensure_business_hours()
        self._get_account(account_id).set_status(AccountStatus.ACTIVE)

    # --- Security ----------------------------------------------------------------------

    def authenticate_client(self, client_id: str, pin: str) -> bool:
        """Authenticate a client by PIN; block after too many failed attempts."""
        client = self._get_client(client_id)
        if client.is_blocked:
            raise ClientBlockedError(f"Client {client_id} is blocked")
        if client.verify_pin(pin):
            client.reset_failed_attempts()
            return True
        client.register_failed_attempt()
        return False

    def _ensure_business_hours(self) -> None:
        """Forbid operations during the nightly lockout window."""
        hour = self._now().hour
        if NIGHT_START <= hour < NIGHT_END:
            raise NightOperationError(
                f"Operations are disabled between {NIGHT_START:02d}:00 and {NIGHT_END:02d}:00"
            )

    # --- Search & analytics ------------------------------------------------------------

    def search_accounts(
        self,
        *,
        owner: str | None = None,
        status: AccountStatus | None = None,
        currency: Currency | None = None,
        account_type: str | None = None,
        min_balance=None,
    ) -> list[AbstractAccount]:
        """Return accounts matching every provided filter."""
        type_cls = ACCOUNT_TYPES[account_type] if account_type else None
        min_bal = Decimal(str(min_balance)) if min_balance is not None else None

        results = []
        for account in self._accounts.values():
            if owner is not None and account.owner != owner:
                continue
            if status is not None and account.status is not status:
                continue
            if currency is not None and account.currency is not currency:
                continue
            if type_cls is not None and type(account) is not type_cls:
                continue
            if min_bal is not None and account.balance < min_bal:
                continue
            results.append(account)
        return results

    def get_total_balance(self, currency: Currency | None = None):
        """Total balances. Per-currency dict, or a single Decimal when ``currency`` is given.

        Balances in different currencies are never summed together.
        """
        if currency is not None:
            return sum(
                (a.balance for a in self._accounts.values() if a.currency is currency),
                Decimal("0.00"),
            )
        totals: dict[str, Decimal] = {}
        for account in self._accounts.values():
            code = account.currency.value
            totals[code] = totals.get(code, Decimal("0.00")) + account.balance
        return totals

    def get_clients_ranking(self) -> list[dict]:
        """Clients ranked by summed account balance, descending.

        The sum ignores currency (a simplification); use only as a relative ranking.
        """
        ranking = []
        for client in self._clients.values():
            total = sum(
                (self._accounts[num].balance for num in client.account_numbers
                 if num in self._accounts),
                Decimal("0.00"),
            )
            ranking.append(
                {
                    "client_id": client.client_id,
                    "full_name": client.full_name,
                    "total": total,
                }
            )
        ranking.sort(key=lambda row: row["total"], reverse=True)
        return ranking
