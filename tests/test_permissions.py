"""Parent controls: the defaults, the persistence, and what happens when nobody answers.

WORKORDER_01 section 25 and section 35A step 6. The recurring theme is that every
uncertain case resolves to "no" -- an unset switch, a damaged file, an unanswerable
prompt. That is the same fail-closed stance ``process_sandbox`` takes, applied to
permission rather than to confinement.
"""

from __future__ import annotations

import json

import pytest

from opennest.agent.tools import Toolbox
from opennest.security import permissions
from opennest.security.permissions import ALLOW, ASK, DENY, ParentControls

# --------------------------------------------------------------------- defaults

def test_cloud_is_off_until_a_parent_turns_it_on() -> None:
    """Section 2311: default OFF "unless explicitly enabled during setup"."""
    controls = ParentControls()
    assert controls.allow_cloud_ai is False
    assert controls.cloud_allowed() is False


def test_the_cautious_defaults_match_the_setup_wizard() -> None:
    """Section 35A step 6 shows exactly these positions on the parent page."""
    controls = ParentControls()
    assert controls.ask_before_cloud_ai is True
    assert controls.state("external_requests") == DENY
    assert controls.state("package_installation") == ASK
    assert controls.state("arduino_upload") == ASK
    assert controls.state("raspberry_pi_deployment") == ASK
    assert controls.github_private_backup is True


def test_every_gate_in_the_table_has_a_setting() -> None:
    """The table is what Settings renders, so a gate with no field would be a blank row."""
    controls = ParentControls()
    for gate in permissions.GATES:
        assert controls.state(gate.name) in permissions.STATES


# ------------------------------------------------------------------ persistence

def test_settings_round_trip(tmp_path) -> None:
    saved = ParentControls(allow_cloud_ai=True, ask_before_cloud_ai=False)
    saved.set_state("external_requests", ALLOW)
    saved.save(tmp_path / "settings.json")

    loaded = ParentControls.load(tmp_path / "settings.json")
    assert loaded.allow_cloud_ai is True
    assert loaded.ask_before_cloud_ai is False
    assert loaded.state("external_requests") == ALLOW


def test_a_missing_file_gives_the_safe_defaults(tmp_path) -> None:
    loaded = ParentControls.load(tmp_path / "never-written.json")
    assert loaded.allow_cloud_ai is False


def test_a_damaged_file_fails_closed_rather_than_open(tmp_path) -> None:
    """A corrupted settings file must not turn cloud on, and must not stop the app."""
    target = tmp_path / "settings.json"
    target.write_text("{not json at all", encoding="utf-8")
    loaded = ParentControls.load(target)
    assert loaded.allow_cloud_ai is False
    assert loaded.state("external_requests") == DENY


def test_a_nonsense_value_is_ignored_in_favour_of_the_default(tmp_path) -> None:
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({
        "allow_cloud_ai": "yes please",          # not a bool
        "external_requests": "sometimes",        # not a known state
        "package_installation": ALLOW,           # this one is fine
    }), encoding="utf-8")

    loaded = ParentControls.load(target)
    assert loaded.allow_cloud_ai is False
    assert loaded.state("external_requests") == DENY
    assert loaded.state("package_installation") == ALLOW


def test_saving_leaves_no_temporary_file_behind(tmp_path) -> None:
    ParentControls().save(tmp_path / "settings.json")
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_an_unknown_control_is_an_error_not_a_silent_no() -> None:
    controls = ParentControls()
    with pytest.raises(KeyError):
        controls.state("allow_everything")
    with pytest.raises(KeyError):
        controls.set_state("allow_everything", ALLOW)


def test_an_unknown_state_is_refused() -> None:
    with pytest.raises(ValueError):
        ParentControls().set_state("arduino_upload", "maybe")


# --------------------------------------------------------------------- deciding

def test_allow_and_deny_need_nobody_to_ask() -> None:
    controls = ParentControls()
    controls.set_state("external_requests", ALLOW)
    assert controls.gate("external_requests") is True
    controls.set_state("external_requests", DENY)
    assert controls.gate("external_requests") is False


def test_ask_with_nobody_to_ask_is_a_no() -> None:
    """The load-bearing one. An application that could not ask has not been told yes."""
    controls = ParentControls()
    controls.set_state("package_installation", ASK)
    assert controls.gate("package_installation") is False


def test_ask_consults_the_approver_and_passes_it_the_gate() -> None:
    controls = ParentControls()
    controls.set_state("arduino_upload", ASK)
    seen = []

    def approver(gate):
        seen.append(gate)
        return True

    assert controls.gate("arduino_upload", approver) is True
    assert [gate.name for gate in seen] == ["arduino_upload"]
    # The approver gets the description Settings shows, so the dialog and the settings
    # page cannot drift apart.
    assert seen[0].label == permissions.GATES_BY_NAME["arduino_upload"].label


def test_a_refusing_approver_is_a_no() -> None:
    controls = ParentControls()
    controls.set_state("package_installation", ASK)
    assert controls.gate("package_installation", lambda gate: False) is False


def test_deny_never_reaches_the_approver() -> None:
    """A parent who set something to Off should not be asked about it again."""
    controls = ParentControls()
    controls.set_state("arduino_upload", DENY)

    def approver(gate):  # pragma: no cover - reaching this is the failure
        raise AssertionError("a denied permission must not prompt")

    assert controls.gate("arduino_upload", approver) is False


# ------------------------------------------------------------------------ cloud

def test_the_warning_is_shown_only_when_cloud_is_on_and_asking_is_on() -> None:
    assert not ParentControls().cloud_needs_confirmation()
    assert ParentControls(allow_cloud_ai=True).cloud_needs_confirmation()
    assert not ParentControls(
        allow_cloud_ai=True, ask_before_cloud_ai=False
    ).cloud_needs_confirmation()


def test_turning_cloud_off_does_not_touch_the_keys(configured_credentials) -> None:
    """Section 2335 in as many words: off must not require deleting the stored keys."""
    controls = ParentControls(allow_cloud_ai=True)
    controls.allow_cloud_ai = False
    assert controls.cloud_allowed() is False
    assert configured_credentials.has_key("anthropic")


# ----------------------------------------------------- reaching the run sandbox

def test_a_project_run_gets_no_network_by_default(project) -> None:
    """The parent control and ``build_profile(allow_network=...)`` finally meet."""
    controls = ParentControls()
    toolbox = Toolbox(project, network_policy=controls.network_for_runs)
    assert toolbox._network_allowed() is False


def test_a_project_run_gets_network_when_a_parent_allows_it(project) -> None:
    controls = ParentControls()
    controls.set_state("external_requests", ALLOW)
    toolbox = Toolbox(project, network_policy=controls.network_for_runs)
    assert toolbox._network_allowed() is True


def test_a_toolbox_with_no_policy_still_denies(project) -> None:
    """Every pre-Phase-6 caller constructs a Toolbox without one. It must not open up."""
    assert Toolbox(project)._network_allowed() is False


def test_a_permission_check_that_breaks_is_not_a_permission_granted(project) -> None:
    def explode() -> bool:
        raise RuntimeError("the dialog blew up")

    assert Toolbox(project, network_policy=explode)._network_allowed() is False
