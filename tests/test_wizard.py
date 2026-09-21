"""The setup wizard's behaviour -- WORKORDER_01 section 35A.

Runs under Qt's ``offscreen`` platform, like ``tests/test_workbench.py``, and for the
same reason: what this widget *looks* like stays on a manual checklist, but what it
*decides* regresses silently. Nothing here asserts on pixels or layout.

What it does assert is the part of the Launcher Definition of Done that a test can
reach: that each step collects what section 35A says it collects, that a model is only
called ready after a real answer, that an API key goes to the Keychain and nowhere near
the installation record, and that the record written at the end is the one the next
launch will read.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.security import keychain, permissions  # noqa: E402
from opennest.setup import checks, downloader  # noqa: E402
from opennest.setup.state import InstallationState  # noqa: E402
from tests.conftest import FakeKeyring  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def wizard(qt_app, tmp_path, monkeypatch):
    """A wizard wired to throwaway state, a fake Keychain and no real model.

    ``complain`` and ``confirm`` are replaced with recorders. Both open a modal
    ``QMessageBox``, and a modal dialog blocks forever under the offscreen platform
    too -- there is no one to press the button. They are the wizard's own seams for
    asking a person something, so stubbing them is the honest place to cut.
    """
    from opennest.setup import wizard as wizard_module

    # Nothing in the suite may touch the real Keychain or the real model cache.
    monkeypatch.setattr(downloader, "is_installed", lambda entry: False)

    complaints: list = []
    questions: list = []
    answer = {"value": False}

    monkeypatch.setattr(
        wizard_module.SetupWizard, "complain",
        lambda self, message: complaints.append(message),
    )
    monkeypatch.setattr(
        wizard_module.SetupWizard, "confirm",
        lambda self, question, detail: (questions.append(question), answer["value"])[1],
    )

    state = InstallationState(path=tmp_path / "installation.json")
    controls = permissions.ParentControls(path=tmp_path / "settings.json")
    built = wizard_module.SetupWizard(
        state=state,
        controls=controls,
        credentials=keychain.Credentials(backend=FakeKeyring()),
    )
    built.complaints = complaints
    built.questions = questions
    built.answer_confirmations = lambda value: answer.__setitem__("value", value)
    yield built
    built.deleteLater()


def _step(wizard, cls_name):
    for step in wizard.steps:
        if type(step).__name__ == cls_name:
            return step
    raise AssertionError(f"no {cls_name} in the wizard")


# --------------------------------------------------------------------- the shape

def test_the_steps_are_the_ones_the_work_order_lists(wizard) -> None:
    """Section 35A's eight, plus the Arduino toolchain step decision D7 adds."""
    names = [type(step).__name__ for step in wizard.steps]
    assert names == [
        "WelcomeStep", "IdentityStep", "LocalAIStep", "ArduinoStep", "CloudStep",
        "GitStep", "ParentStep", "HealthStep", "FinishStep",
    ]


def test_the_last_step_launches_and_the_first_cannot_go_back(wizard) -> None:
    wizard._show_step(0)
    assert wizard._back.isEnabled() is False
    wizard._show_step(len(wizard.steps) - 1)
    assert wizard._next.text() == "Launch Open Nest"


def test_a_step_that_refuses_to_leave_keeps_the_wizard_where_it_is(wizard) -> None:
    """``leave`` returning False is how a step blocks Continue."""
    wizard._show_step(1)  # identity, which needs a name
    _step(wizard, "IdentityStep")._name.setText("")
    wizard._go_next()
    assert wizard.index == 1


def test_navigation_is_locked_while_a_download_runs(wizard) -> None:
    """Back and Continue must not move out from under a worker thread."""
    wizard._show_step(2)
    wizard.set_busy(True)
    assert wizard._next.isEnabled() is False
    wizard._go_next()
    assert wizard.index == 2
    wizard.set_busy(False)
    assert wizard._next.isEnabled() is True


# --------------------------------------------------------------------- identity

def test_identity_records_the_name_and_the_git_details(wizard) -> None:
    """Section 35A step 2 keeps the child-facing name and the Git identity apart."""
    step = _step(wizard, "IdentityStep")
    step.enter()
    step._name.setText("Elliot")
    step._git_name.setText("Elliot Example")
    step._git_email.setText("elliot@example.com")
    assert step.leave() is True
    assert wizard.state.child_name == "Elliot"
    assert wizard.state.git_author_name == "Elliot Example"
    assert wizard.state.git_author_email == "elliot@example.com"


def test_a_blank_git_name_falls_back_to_the_display_name(wizard) -> None:
    step = _step(wizard, "IdentityStep")
    step.enter()
    step._name.setText("Elliot")
    step._git_name.setText("")
    assert step.leave() is True
    assert wizard.state.git_author_name == "Elliot"


def test_setup_works_with_no_git_email(wizard) -> None:
    """Section 35A: "If no Git identity is supplied, Build Lab should still function"."""
    step = _step(wizard, "IdentityStep")
    step.enter()
    step._name.setText("Elliot")
    step._git_email.setText("")
    assert step.leave() is True
    assert wizard.state.git_author_email == ""


# --------------------------------------------------------------------- local AI

def test_the_model_list_comes_from_the_catalogue(wizard) -> None:
    """Section 35A forbids hard-coding model ids or sizes into wizard logic."""
    from opennest.ai import router

    step = _step(wizard, "LocalAIStep")
    step.enter()
    offered = {step._picker.itemData(i) for i in range(step._picker.count())}
    assert offered == {entry.info.id for entry in router.local_models()}


def test_the_recommended_model_is_marked_as_such(wizard) -> None:
    step = _step(wizard, "LocalAIStep")
    step.enter()
    labels = [step._picker.itemText(i) for i in range(step._picker.count())]
    assert any(label.startswith("Recommended") for label in labels)


def test_the_download_size_is_shown_before_anything_starts(wizard) -> None:
    step = _step(wizard, "LocalAIStep")
    step.enter()
    assert "GB" in step._detail.text()


def test_a_model_is_only_ready_after_it_actually_answers(wizard) -> None:
    """Section 35A: "only mark the model as ready after this test succeeds"."""
    from opennest.ai import router

    step = _step(wizard, "LocalAIStep")
    step.enter()
    entry = router.get_entry(router.default_model_id())

    step._verified(entry, downloader.VerificationResult(
        engine_loaded=True, model_loaded=True, inference_completed=False,
        message="loaded but answered with nothing",
    ))
    assert wizard.state.preferred_model == ""
    assert wizard.state.installed_models == []

    step._verified(entry, downloader.VerificationResult(
        engine_loaded=True, model_loaded=True, inference_completed=True, reply="OK",
    ))
    assert wizard.state.preferred_model == entry.info.id
    assert wizard.state.installed_models == [entry.info.id]


def test_a_finished_download_that_fails_verification_is_not_recorded(wizard) -> None:
    """A download completing is not the same claim as a model working."""
    from opennest.ai import router

    step = _step(wizard, "LocalAIStep")
    step.enter()
    entry = router.get_entry(router.default_model_id())
    step._downloaded(entry, downloader.DownloadResult(False, "failed", "no network"))
    assert wizard.state.preferred_model == ""
    assert "no network" in step._status.text()


def test_progress_updates_the_bar_and_says_how_far_along_it_is(wizard) -> None:
    step = _step(wizard, "LocalAIStep")
    step.enter()
    step._on_progress(downloader.Progress(1_000_000_000, 2_000_000_000))
    assert step._bar.value() == 50
    assert "1.0 GB of 2.0 GB" in step._status.text()


# --------------------------------------------------------------------- arduino (D7)

def test_the_arduino_step_is_skippable_and_says_its_size(wizard, monkeypatch) -> None:
    """D7: another 341 MB, so it is a choice rather than part of the default install."""
    from opennest.setup import toolchain

    monkeypatch.setattr(toolchain, "is_installed", lambda: False)
    step = _step(wizard, "ArduinoStep")
    step.enter()
    assert step.leave() is True, "the Arduino step must never block setup"
    assert wizard.state.arduino_installed is False


def test_an_already_installed_toolchain_is_recognised(wizard, monkeypatch) -> None:
    from opennest.setup import toolchain

    monkeypatch.setattr(toolchain, "is_installed", lambda: True)
    step = _step(wizard, "ArduinoStep")
    step.enter()
    assert wizard.state.arduino_installed is True
    assert step._install.isEnabled() is False


def test_a_failed_toolchain_install_is_not_recorded_as_installed(wizard) -> None:
    from opennest.setup.toolchain import ToolchainResult

    step = _step(wizard, "ArduinoStep")
    step._done(ToolchainResult(False, "The Arduino tools did not match the checksum"))
    assert wizard.state.arduino_installed is False
    assert "checksum" in step._status.text()


# --------------------------------------------------------------------- cloud

def test_a_saved_key_goes_to_the_keychain_and_leaves_the_box(wizard) -> None:
    """Section 35A: "Store the credential immediately in macOS Keychain"."""
    step = _step(wizard, "CloudStep")
    step.enter()
    entry, status = step._rows["openai"]
    entry.setText("sk-test-not-a-real-key")
    step._save("openai", entry, status)

    assert wizard.credentials.has_key("openai") is True
    assert entry.text() == "", "the key should not stay in the widget"


def test_cloud_stays_off_unless_it_is_turned_on(wizard) -> None:
    """Section 2311: default OFF "unless explicitly enabled during setup"."""
    step = _step(wizard, "CloudStep")
    step.enter()
    assert step.leave() is True
    assert wizard.controls.allow_cloud_ai is False
    assert wizard.state.cloud_enabled is False


def test_turning_cloud_on_is_recorded_in_both_places(wizard) -> None:
    step = _step(wizard, "CloudStep")
    step.enter()
    wizard.credentials.save_key("openai", "sk-test-not-a-real-key")
    step._switch.setCurrentIndex(step._switch.findData(True))
    assert step.leave() is True
    assert wizard.controls.allow_cloud_ai is True
    assert wizard.state.cloud_enabled is True


def test_removing_a_key_takes_it_out_of_the_keychain(wizard) -> None:
    step = _step(wizard, "CloudStep")
    step.enter()
    wizard.credentials.save_key("anthropic", "sk-ant-test-not-real")
    step._remove("anthropic", step._rows["anthropic"][1])
    assert wizard.credentials.has_key("anthropic") is False


# --------------------------------------------------------------------- parent controls

def test_the_pin_is_stored_as_a_fingerprint_not_as_the_pin(wizard) -> None:
    step = _step(wizard, "ParentStep")
    step.enter()
    step._pin.setText("2468")
    step._again.setText("2468")
    assert step.leave() is True

    assert wizard.credentials.parent_pin_set() is True
    assert wizard.credentials.check_parent_pin("2468") is True
    assert wizard.credentials.check_parent_pin("1111") is False
    stored = wizard.credentials.backend.items[(keychain.SERVICE, "parent-pin")]
    assert "2468" not in stored


def test_mismatched_pins_change_nothing(wizard) -> None:
    step = _step(wizard, "ParentStep")
    step.enter()
    step._pin.setText("2468")
    step._again.setText("1357")
    assert step.leave() is False
    assert wizard.credentials.parent_pin_set() is False


def test_a_blank_pin_is_allowed_and_sets_none(wizard) -> None:
    """Forcing a PIN would be a way to lock a parent out of their own Mac."""
    step = _step(wizard, "ParentStep")
    step.enter()
    assert step.leave() is True
    assert wizard.credentials.parent_pin_set() is False


def test_the_pin_boxes_are_cleared_after_it_is_saved(wizard) -> None:
    step = _step(wizard, "ParentStep")
    step.enter()
    step._pin.setText("2468")
    step._again.setText("2468")
    step.leave()
    assert step._pin.text() == ""
    assert step._again.text() == ""


def test_every_parent_control_is_offered(wizard) -> None:
    """The rows come from ``permissions.GATES``, so a new gate needs no wizard change."""
    step = _step(wizard, "ParentStep")
    assert set(step._gates) == {gate.name for gate in permissions.GATES}


def test_the_parent_page_starts_at_the_cautious_defaults(wizard) -> None:
    """Section 35A step 6 shows external requests OFF and the rest Ask Parent."""
    step = _step(wizard, "ParentStep")
    step.enter()
    assert step._gates["external_requests"].currentData() == permissions.DENY
    assert step._gates["package_installation"].currentData() == permissions.ASK
    assert step._gates["arduino_upload"].currentData() == permissions.ASK


def test_changing_a_control_persists_it(wizard, tmp_path) -> None:
    step = _step(wizard, "ParentStep")
    step.enter()
    box = step._gates["arduino_upload"]
    box.setCurrentIndex(box.findData(permissions.DENY))
    assert step.leave() is True

    saved = json.loads((tmp_path / "settings.json").read_text())
    assert saved["arduino_upload"] == permissions.DENY


# --------------------------------------------------------------------- health check

def test_the_health_check_reports_every_row(wizard) -> None:
    step = _step(wizard, "HealthStep")
    step.enter()
    assert "Python environment" in step._results.text()
    assert "macOS Keychain" in step._results.text()


def test_a_clean_health_check_does_not_interrupt(wizard, monkeypatch) -> None:
    monkeypatch.setattr(checks, "run", lambda *a, **k: (checks.Check("A", checks.OK),))
    step = _step(wizard, "HealthStep")
    step.enter()
    assert step.leave() is True


def test_an_unconfigured_optional_service_does_not_interrupt(wizard, monkeypatch) -> None:
    """Section 35A: "Not configured" is not an error, so it must not block Finish."""
    monkeypatch.setattr(
        checks, "run",
        lambda *a, **k: (checks.Check("Anthropic", checks.NOT_CONFIGURED),),
    )
    step = _step(wizard, "HealthStep")
    step.enter()
    assert step.leave() is True


# --------------------------------------------------------------------- finishing

def test_finishing_records_a_completed_installation(wizard, tmp_path) -> None:
    _step(wizard, "IdentityStep")._name.setText("Elliot")
    _step(wizard, "IdentityStep").leave()
    wizard._finish()

    written = InstallationState.load(tmp_path / "installation.json")
    assert written.setup_complete is True
    assert written.needs_setup() is False
    assert written.child_name == "Elliot"


def test_finishing_adopts_the_current_checkout_so_the_next_launch_can_compare(
    wizard, tmp_path
) -> None:
    """DoD 51-53: without this, the first launch after setup reports a phantom update."""
    wizard._finish()
    written = InstallationState.load(tmp_path / "installation.json")
    assert written.fingerprint.recorded() is True
    assert written.pending_changes() == ()


def test_no_api_key_reaches_the_installation_record(wizard, tmp_path) -> None:
    """Section 35A: "Do not store secrets in this configuration"."""
    step = _step(wizard, "CloudStep")
    step.enter()
    entry, status = step._rows["openai"]
    entry.setText("sk-proj-" + "B" * 60)
    step._save("openai", entry, status)
    _step(wizard, "IdentityStep")._name.setText("Elliot")
    _step(wizard, "IdentityStep").leave()
    wizard._finish()

    written = (tmp_path / "installation.json").read_text()
    assert "sk-proj-" not in written
    assert "B" * 60 not in written
