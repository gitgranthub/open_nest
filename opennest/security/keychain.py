"""Credentials, and the one place they are allowed to live.

WORKORDER_01 section 22 names the macOS Keychain as the only permitted store for an API
key, and lists everywhere it must never appear: project files, JSON configuration,
plaintext preferences, logs, prompts, Git repositories, project memory, chat archives.

That list is the reason this module is small and has no file I/O of any kind. There is no
cache, no "remember for this session" file, no debug dump. A key is read from the
Keychain at the moment a request is built and is never written down by Open Nest. The
provider layer keeps it in an Authorization header and nowhere else, and
``test_a_saved_key_reaches_no_file_on_disk`` walks the whole containment root to check.

Phase 1 verified the backend itself (SPIKES.md section 6): round-trip, overwrite, long
values, delete, absent-key returning ``None``, and ``PasswordDeleteError`` on deleting an
absent key, with no interactive prompt for the application's own items.

The parent PIN lives here too, as a hash rather than the PIN. Section 25 asks for a
"lightweight PIN" and warns against over-engineering, so this is PBKDF2 with a random
salt -- enough that reading the Keychain item does not hand someone the PIN, and not a
credential system. It is a speed bump on a child's own Mac, which is what it is for.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from opennest import APP_NAME

#: The Keychain service every Open Nest item is filed under.
SERVICE = APP_NAME

#: Keychain accounts. Cloud providers are keyed by the ``provider`` field in models.json,
#: so adding a provider to the catalogue needs no change here.
PARENT_PIN_ACCOUNT = "parent-pin"

#: Providers Open Nest knows how to hold a key for.
CLOUD_PROVIDERS: tuple[str, ...] = ("openai", "anthropic")

#: Human names, for messages a parent reads.
PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic"}

#: PBKDF2 rounds for the parent PIN. A PIN is four digits, so no iteration count makes it
#: brute-force proof; this is only about not storing it in the clear.
_PIN_ROUNDS = 200_000


class CredentialError(Exception):
    """The Keychain could not be used. Phrased for a parent to read.

    Never carries a key or a PIN. An exception message is one of the places section 22
    forbids, because it ends up in a dialog, a traceback, or a bug report.
    """


@dataclass(frozen=True)
class ProviderStatus:
    """What Settings shows for one cloud provider, without reading the key."""

    provider: str
    label: str
    configured: bool

    @property
    def summary(self) -> str:
        return "API key saved" if self.configured else "Not configured"


class Credentials:
    """Read and write Open Nest's Keychain items.

    The backend is injectable so the test suite never touches the real Keychain -- the
    same reason the agent tests use a scripted provider. Nothing else about the class
    changes between the two.
    """

    def __init__(self, backend=None, service: str = SERVICE) -> None:
        self._backend = backend
        self.service = service

    # -- backend ------------------------------------------------------------

    @property
    def backend(self):
        if self._backend is None:
            self._backend = _real_keyring()
        return self._backend

    def available(self) -> bool:
        """Whether the Keychain can actually be reached.

        Probed by using it, not by checking that the library imports -- the same
        reasoning as ``process_sandbox.sandbox_available``. A keyring installed with no
        usable backend imports perfectly and fails on the first read.
        """
        try:
            self.backend.get_password(self.service, "__probe__")
        except Exception:
            return False
        return True

    # -- cloud API keys -----------------------------------------------------

    def save_key(self, provider: str, key: str) -> None:
        """Store a provider's API key. Overwrites any previous one."""
        provider = _require_known(provider)
        key = (key or "").strip()
        if not key:
            raise CredentialError("That API key was empty, so nothing was saved.")
        try:
            self.backend.set_password(self.service, provider, key)
        except Exception as exc:
            raise CredentialError(_backend_problem(exc)) from None

    def get_key(self, provider: str) -> str | None:
        """The stored key, or None. Callers must not log or persist the result."""
        provider = _require_known(provider)
        try:
            value = self.backend.get_password(self.service, provider)
        except Exception as exc:
            raise CredentialError(_backend_problem(exc)) from None
        return value or None

    def has_key(self, provider: str) -> bool:
        """Whether a key is configured, without the caller ever holding it."""
        try:
            return self.get_key(provider) is not None
        except CredentialError:
            return False

    def delete_key(self, provider: str) -> bool:
        """Remove a key. Returns whether there was one. Deleting an absent key is fine."""
        provider = _require_known(provider)
        try:
            self.backend.delete_password(self.service, provider)
        except Exception as exc:
            if _is_missing_entry(exc):
                return False
            raise CredentialError(_backend_problem(exc)) from None
        return True

    def statuses(self) -> tuple[ProviderStatus, ...]:
        """One row per provider for Settings. Reads no key into the caller's hands."""
        return tuple(
            ProviderStatus(provider, PROVIDER_LABELS.get(provider, provider),
                           self.has_key(provider))
            for provider in CLOUD_PROVIDERS
        )

    # -- parent PIN ---------------------------------------------------------

    def set_parent_pin(self, pin: str) -> None:
        """Store a hash of the PIN. The PIN itself is never written anywhere."""
        pin = (pin or "").strip()
        if len(pin) < 4:
            raise CredentialError("A parent PIN needs at least four characters.")
        try:
            self.backend.set_password(self.service, PARENT_PIN_ACCOUNT, _hash_pin(pin))
        except Exception as exc:
            raise CredentialError(_backend_problem(exc)) from None

    def parent_pin_set(self) -> bool:
        try:
            return bool(self.backend.get_password(self.service, PARENT_PIN_ACCOUNT))
        except Exception:
            return False

    def check_parent_pin(self, pin: str) -> bool:
        """Whether this PIN matches. False when no PIN has been set.

        Deliberately false rather than true for an unset PIN: the caller decides what an
        unconfigured parent gate means, and a helper that answers "yes" to every PIN
        because none was configured is the wrong default to have lying around.
        """
        try:
            stored = self.backend.get_password(self.service, PARENT_PIN_ACCOUNT)
        except Exception:
            return False
        if not stored:
            return False
        return _verify_pin(pin or "", stored)

    def clear_parent_pin(self) -> bool:
        try:
            self.backend.delete_password(self.service, PARENT_PIN_ACCOUNT)
        except Exception as exc:
            if _is_missing_entry(exc):
                return False
            raise CredentialError(_backend_problem(exc)) from None
        return True


_default: Credentials | None = None


def default() -> Credentials:
    """The application's credential store."""
    global _default
    if _default is None:
        _default = Credentials()
    return _default


# --------------------------------------------------------------------------- internals

def _real_keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - keyring is a base dependency
        raise CredentialError(
            "Open Nest cannot reach the macOS Keychain, so it cannot store an API key. "
            "Run Setup again to repair the installation."
        ) from exc
    return keyring


def _require_known(provider: str) -> str:
    name = (provider or "").strip().lower()
    if name not in CLOUD_PROVIDERS:
        known = ", ".join(CLOUD_PROVIDERS)
        raise CredentialError(f"Open Nest has no cloud service called {provider!r}. "
                              f"It knows about: {known}.")
    return name


def _backend_problem(exc: Exception) -> str:
    """A message about the Keychain that cannot contain what was being stored.

    ``exc`` is deliberately not interpolated. A keyring backend is free to include the
    value it was handed in an error, and that value is the key.
    """
    return (
        "Open Nest could not use the macOS Keychain "
        f"({type(exc).__name__}). Nothing was saved. A parent can try again in Settings."
    )


def _is_missing_entry(exc: Exception) -> bool:
    """Deleting something that was never there is not an error worth raising."""
    return type(exc).__name__ in ("PasswordDeleteError", "KeyError")


def _hash_pin(pin: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, _PIN_ROUNDS)
    return f"pbkdf2_sha256${_PIN_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_pin(pin: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest_hex)
