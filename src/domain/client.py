"""Client domain model."""

from __future__ import annotations

import hashlib
import uuid

from .enums import ClientStatus
from .errors import InvalidOperationError, UnderageError

MIN_AGE = 18
MAX_LOGIN_ATTEMPTS = 3


def _hash_pin(pin: str) -> str:
    """Hash a PIN with sha256.

    Simplified for this project: real systems must salt and use a slow KDF (bcrypt/argon2).
    """
    return hashlib.sha256(str(pin).encode("utf-8")).hexdigest()


class Client:
    """A bank client who can own several accounts and authenticate with a PIN."""

    def __init__(
        self,
        full_name: str,
        age: int,
        *,
        pin: str,
        client_id: str | None = None,
        contacts: dict | None = None,
    ) -> None:
        if not isinstance(full_name, str) or not full_name.strip():
            raise InvalidOperationError("full_name must be a non-empty string")
        if not isinstance(age, int) or isinstance(age, bool):
            raise InvalidOperationError("age must be an integer")
        if age < MIN_AGE:
            raise UnderageError(f"Client must be at least {MIN_AGE}; got {age}")
        if pin is None or str(pin) == "":
            raise InvalidOperationError("pin is required")

        self._client_id = client_id if client_id else uuid.uuid4().hex[:8].upper()
        self._full_name = full_name.strip()
        self._age = age
        self._contacts = dict(contacts or {})
        self._pin_hash = _hash_pin(pin)
        self._status = ClientStatus.ACTIVE
        self._account_numbers: list[str] = []
        self._failed_attempts = 0
        self.suspicious_flags: list[str] = []

    # --- Read-only access --------------------------------------------------------------

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def full_name(self) -> str:
        return self._full_name

    @property
    def age(self) -> int:
        return self._age

    @property
    def contacts(self) -> dict:
        return dict(self._contacts)

    @property
    def status(self) -> ClientStatus:
        return self._status

    @property
    def account_numbers(self) -> list[str]:
        return list(self._account_numbers)

    @property
    def failed_attempts(self) -> int:
        return self._failed_attempts

    @property
    def is_blocked(self) -> bool:
        return self._status is ClientStatus.BLOCKED

    # --- Account links -----------------------------------------------------------------

    def add_account_number(self, number: str) -> None:
        if number not in self._account_numbers:
            self._account_numbers.append(number)

    def remove_account_number(self, number: str) -> None:
        if number in self._account_numbers:
            self._account_numbers.remove(number)

    # --- Security ----------------------------------------------------------------------

    def verify_pin(self, pin: str) -> bool:
        return self._pin_hash == _hash_pin(pin)

    def register_failed_attempt(self) -> None:
        """Count a failed login; block the client after too many attempts."""
        self._failed_attempts += 1
        self.flag_suspicious(f"failed login attempt #{self._failed_attempts}")
        if self._failed_attempts >= MAX_LOGIN_ATTEMPTS:
            self.block("too many failed login attempts")

    def reset_failed_attempts(self) -> None:
        self._failed_attempts = 0

    def block(self, reason: str) -> None:
        self._status = ClientStatus.BLOCKED
        self.flag_suspicious(f"blocked: {reason}")

    def flag_suspicious(self, reason: str) -> None:
        self.suspicious_flags.append(reason)

    # --- Representation ----------------------------------------------------------------

    def get_client_info(self) -> dict:
        return {
            "client_id": self._client_id,
            "full_name": self._full_name,
            "age": self._age,
            "status": self._status.value,
            "contacts": dict(self._contacts),
            "account_numbers": list(self._account_numbers),
            "failed_attempts": self._failed_attempts,
            "suspicious_flags": list(self.suspicious_flags),
        }

    def __str__(self) -> str:
        return (
            f"Client {self._client_id} | {self._full_name} | {self._status.value.upper()} | "
            f"{len(self._account_numbers)} account(s)"
        )
