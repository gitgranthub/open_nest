"""Credentials: where they go, and everywhere they must not.

WORKORDER_01 section 22 is a list of places an API key must never appear. Most of these
tests are that list, turned into assertions. The Keychain backend itself was measured in
Phase 1 (SPIKES.md section 6); what is checked here is Open Nest's behaviour around it.
"""

from __future__ import annotations

import pytest

from opennest import diagnostics
from opennest.security import keychain, permissions
from tests.conftest import FakeKeyring

ANTHROPIC_KEY = "sk-ant-api03-" + "Z9" * 30
OPENAI_KEY = "sk-proj-" + "Q7" * 30


# --------------------------------------------------------------- storing a key

def test_a_key_round_trips(credentials) -> None:
    credentials.save_key("anthropic", ANTHROPIC_KEY)
    assert credentials.get_key("anthropic") == ANTHROPIC_KEY
    assert credentials.has_key("anthropic")


def test_saving_again_replaces_rather_than_duplicates(credentials) -> None:
    credentials.save_key("openai", OPENAI_KEY)
    credentials.save_key("openai", OPENAI_KEY + "-second")
    assert credentials.get_key("openai") == OPENAI_KEY + "-second"


def test_an_absent_key_is_none_not_an_error(credentials) -> None:
    assert credentials.get_key("openai") is None
    assert not credentials.has_key("openai")


def test_deleting_a_key_that_was_never_there_is_not_an_error(credentials) -> None:
    """SPIKES.md section 6 measured the backend raising here. It must not surface."""
    assert credentials.delete_key("openai") is False


def test_deleting_reports_that_there_was_one(credentials) -> None:
    credentials.save_key("openai", OPENAI_KEY)
    assert credentials.delete_key("openai") is True
    assert not credentials.has_key("openai")


def test_an_empty_key_is_refused(credentials) -> None:
    with pytest.raises(keychain.CredentialError):
        credentials.save_key("anthropic", "   ")


def test_an_unknown_service_is_refused(credentials) -> None:
    with pytest.raises(keychain.CredentialError):
        credentials.save_key("some-other-ai", ANTHROPIC_KEY)


def test_statuses_report_configuration_without_the_key(credentials) -> None:
    credentials.save_key("anthropic", ANTHROPIC_KEY)
    rendered = [f"{s.label}: {s.summary}" for s in credentials.statuses()]
    assert "Anthropic: API key saved" in rendered
    assert "OpenAI: Not configured" in rendered
    assert not any(ANTHROPIC_KEY in line for line in rendered)


def test_a_backend_failure_message_cannot_contain_what_it_was_storing() -> None:
    """A keyring backend is free to put the value it was handed into its exception.

    That exception text goes into a dialog and then into a bug report, so the message
    is built from the exception's *type* and never from its text.
    """

    class Exploding:
        def get_password(self, service, account):
            return None

        def set_password(self, service, account, value):
            raise RuntimeError(f"could not store {value}")

        def delete_password(self, service, account):
            raise RuntimeError("no")

    store = keychain.Credentials(backend=Exploding())
    with pytest.raises(keychain.CredentialError) as caught:
        store.save_key("anthropic", ANTHROPIC_KEY)
    assert ANTHROPIC_KEY not in str(caught.value)


# --------------------------------------------------------------- the parent PIN

def test_the_pin_is_stored_as_a_hash_not_as_the_pin() -> None:
    backend = FakeKeyring()
    store = keychain.Credentials(backend=backend)
    store.set_parent_pin("2468")

    stored = backend.items[(keychain.SERVICE, keychain.PARENT_PIN_ACCOUNT)]
    assert "2468" not in stored
    assert stored.startswith("pbkdf2_sha256$")


def test_the_right_pin_is_accepted_and_a_wrong_one_is_not(credentials) -> None:
    credentials.set_parent_pin("2468")
    assert credentials.check_parent_pin("2468")
    assert not credentials.check_parent_pin("2469")
    assert not credentials.check_parent_pin("")


def test_two_identical_pins_hash_differently(credentials) -> None:
    """Salted, so the stored value does not reveal that two Macs share a PIN."""
    credentials.set_parent_pin("2468")
    first = credentials.backend.items[(keychain.SERVICE, keychain.PARENT_PIN_ACCOUNT)]
    credentials.set_parent_pin("2468")
    second = credentials.backend.items[(keychain.SERVICE, keychain.PARENT_PIN_ACCOUNT)]
    assert first != second
    assert credentials.check_parent_pin("2468")


def test_an_unset_pin_matches_nothing(credentials) -> None:
    """Not "everything matches". The caller decides what no-PIN-configured means."""
    assert not credentials.parent_pin_set()
    assert not credentials.check_parent_pin("")
    assert not credentials.check_parent_pin("0000")


def test_a_pin_must_be_long_enough_to_be_worth_having(credentials) -> None:
    with pytest.raises(keychain.CredentialError):
        credentials.set_parent_pin("12")


def test_a_damaged_pin_record_denies_rather_than_admits(credentials) -> None:
    credentials.backend.items[(keychain.SERVICE, keychain.PARENT_PIN_ACCOUNT)] = "rubbish"
    assert credentials.parent_pin_set()
    assert not credentials.check_parent_pin("2468")


# ------------------------------------------- the places a key must never appear

def test_settings_refuse_to_hold_anything_credential_shaped(tmp_path) -> None:
    """Section 22 names plaintext preferences. Nothing puts a key here -- which is
    exactly why the guard is worth having: the failure it catches is a future change."""
    controls = permissions.ParentControls()
    controls.save(tmp_path / "settings.json")  # The ordinary case still works.

    # A realistic key, not "sk-ant-api03-xxxx": the scanner deliberately ignores
    # obvious placeholders, so a placeholder here would test nothing.
    controls.arduino_upload = ANTHROPIC_KEY
    with pytest.raises(ValueError):
        controls.save(tmp_path / "settings.json")


def test_the_settings_file_holds_switches_and_nothing_else(tmp_path, credentials) -> None:
    credentials.save_key("anthropic", ANTHROPIC_KEY)
    controls = permissions.ParentControls(allow_cloud_ai=True)
    target = controls.save(tmp_path / "settings.json")
    written = target.read_text(encoding="utf-8")
    assert ANTHROPIC_KEY not in written
    assert '"allow_cloud_ai": true' in written


def test_the_diagnostic_report_never_contains_a_key(configured_credentials) -> None:
    """Section 33: logs must not contain API keys or Keychain contents."""
    controls = permissions.ParentControls(allow_cloud_ai=True)
    text = diagnostics.report(controls, configured_credentials)

    saved = configured_credentials.get_key("anthropic")
    assert saved and saved not in text
    assert configured_credentials.get_key("openai") not in text
    # It should still be *useful*: configured or not is the fact support needs.
    assert "Anthropic API key: API key saved" in text
    assert "Cloud AI: on" in text


def test_the_diagnostic_report_says_when_a_key_is_absent(credentials) -> None:
    text = diagnostics.report(permissions.ParentControls(), credentials)
    assert "Anthropic API key: Not configured" in text
    assert "Parent PIN: not set" in text
