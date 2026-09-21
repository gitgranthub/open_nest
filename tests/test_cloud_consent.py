"""DoD 35-37, and the Phase 6 exit criterion, end to end.

    35. Parent has optionally configured an Anthropic API key.
    36. Child attempts to switch to Claude.
    37. Open Nest displays the configured cloud-use warning or parent approval step.

Driven through the real ``MainWindow._switch_model``, because the thing worth proving is
the *order* -- allowed at all, then consented to, then switched -- and a test of a copy
of that logic would prove nothing. Two things are patched: the provider factory, so no
model is loaded and no socket is opened, and the warning dialog, so the test can answer
it. What the dialog says is checked separately, as text.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import ModelInfo, Reply  # noqa: E402
from opennest.security.permissions import ParentControls  # noqa: E402
from opennest.ui import consent  # noqa: E402
from opennest.ui.workbench import Workbench  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

CLAUDE = ModelInfo(
    id="claude-sonnet", name="Claude", provider="anthropic",
    requires_internet=True, may_cost_money=True, supports_images=True,
    # The catalogue's own numbers, so the budget test compares two real policies.
    context_policy={
        "max_context_tokens": 48000,
        "rollover_threshold": 36000,
        "memory_reserved_tokens": 6000,
    },
)


@pytest.fixture(scope="session")
def qt_app():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - PySide6 is an application dependency
        pytest.skip("PySide6 is not installed")
    return QApplication.instance() or QApplication([])


def cloud_provider() -> ScriptedProvider:
    """A stand-in for Claude that is loadable without a key or a network."""
    provider = ScriptedProvider([Reply(text="Sure.")])
    provider.info = CLAUDE
    return provider


@pytest.fixture
def bench(qt_app, project, monkeypatch, configured_credentials):
    """A Workbench wired to a MainWindow, with nothing that loads or dials out."""
    from opennest.ui import main_window as module

    local = ScriptedProvider([Reply(text="Done.")])
    monkeypatch.setattr(module, "run_in_thread", lambda *a, **k: None)
    monkeypatch.setattr(module, "build_provider", lambda model_id, **kw: (
        cloud_provider() if model_id == "claude-sonnet" else local
    ))

    window = module.MainWindow(credentials=configured_credentials)
    window.controls = ParentControls(allow_cloud_ai=True)
    window._provider = local

    controller = AgentController(project, local, Toolbox(project))
    workbench = Workbench(
        project, controller, None,
        allow_cloud=True, credentials=configured_credentials,
    )
    workbench.model_change_requested.connect(window._switch_model)
    window._workbench = workbench
    window._controller = controller
    return window, workbench, controller


# --------------------------------------------------------------- DoD 35 to 37

def test_switching_to_claude_shows_the_warning_and_then_switches(bench, monkeypatch):
    """DoD 36 and 37: the child asks for Claude, and is shown the warning first."""
    window, workbench, controller = bench
    shown = []
    monkeypatch.setattr(consent, "confirm_cloud_use",
                        lambda parent, info: shown.append(info) or True)

    workbench.model_change_requested.emit("claude-sonnet")

    assert [info.name for info in shown] == ["Claude"]
    assert controller.provider.info.id == "claude-sonnet"
    assert workbench.current_model_id() == "claude-sonnet"


def test_declining_the_warning_leaves_the_model_alone(bench, monkeypatch):
    """The refusal path, which matters more than the happy one: nothing may change."""
    window, workbench, controller = bench
    monkeypatch.setattr(consent, "confirm_cloud_use", lambda parent, info: False)

    workbench.model_change_requested.emit("claude-sonnet")

    assert controller.provider.info.id == "fake"
    # And the picker goes back, so what is on screen matches what is answering.
    assert workbench.current_model_id() != "claude-sonnet"


def test_with_asking_turned_off_there_is_no_warning(bench, monkeypatch):
    """Section 22's checkbox: a parent may choose not to be asked every time."""
    window, workbench, controller = bench
    window.controls = ParentControls(allow_cloud_ai=True, ask_before_cloud_ai=False)
    monkeypatch.setattr(consent, "confirm_cloud_use", lambda parent, info: (_ for _ in ()).throw(
        AssertionError("the warning must not appear when asking is off")
    ))

    workbench.model_change_requested.emit("claude-sonnet")
    assert controller.provider.info.id == "claude-sonnet"


def test_cloud_off_refuses_before_any_warning_is_reached(bench, monkeypatch):
    """The master switch comes first. Nothing is asked, because nothing is on offer."""
    window, workbench, controller = bench
    window.controls = ParentControls(allow_cloud_ai=False)
    monkeypatch.setattr(consent, "confirm_cloud_use", lambda parent, info: (_ for _ in ()).throw(
        AssertionError("cloud is off; there is nothing to consent to")
    ))
    told = []
    monkeypatch.setattr(
        "opennest.ui.main_window.QMessageBox.information",
        lambda *args, **kwargs: told.append(args[-1]),
    )

    workbench.model_change_requested.emit("claude-sonnet")

    assert controller.provider.info.id == "fake"
    assert told and "cloud AI is turned off" in told[0]


def test_switching_moves_the_context_budget_too(bench, monkeypatch):
    """A cloud model has its own budget; carrying the old one over would be wrong."""
    from opennest.memory.manager import MemoryManager

    window, workbench, controller = bench
    controller.memory = MemoryManager.for_provider(controller.project, controller.provider)
    before = controller.memory.policy.max_context_tokens
    monkeypatch.setattr(consent, "confirm_cloud_use", lambda parent, info: True)

    workbench.model_change_requested.emit("claude-sonnet")

    assert controller.memory.policy.max_context_tokens != before
    assert controller.memory.budget.reported == 0


# ------------------------------------------------------- what the warning says

def test_the_warning_names_the_company_not_the_product() -> None:
    """Section 24: "Information from this project may be sent to Anthropic"."""
    text = consent.cloud_warning_text(CLAUDE)
    assert "Claude uses the internet." in text
    assert "may be sent to Anthropic" in text
    assert "Using Claude may also cost money." in text


def test_the_warning_does_not_pretend_it_stays_on_the_mac() -> None:
    """Section 24 forbids implying cloud interactions remain on-device."""
    text = consent.cloud_warning_text(CLAUDE).lower()
    assert "private" not in text
    assert "on this mac" not in text
    assert "stays" not in text


def test_a_free_model_is_not_told_it_costs_money() -> None:
    free = ModelInfo(id="x", name="Something", provider="openai",
                     requires_internet=True, may_cost_money=False)
    assert "cost money" not in consent.cloud_warning_text(free)


def test_the_api_key_explanation_is_the_one_the_work_order_asked_for() -> None:
    """Section 23, with the product renamed."""
    text = consent.API_KEY_EXPLANATION
    assert "secret password" in text
    assert "A parent can add one here." in text
    assert "never send an API key to another person" in text
    assert "Build Lab" not in text


# --------------------------------------------- the picker, and cloud turned off

def test_the_picker_shows_cloud_models_but_says_what_is_missing(
    qt_app, project, credentials
) -> None:
    """DESIGN_DOC section 13: the INTERNET section is visible even when unusable."""
    controller = AgentController(project, ScriptedProvider([]), Toolbox(project))
    workbench = Workbench(project, controller, None,
                          allow_cloud=False, credentials=credentials)

    labels = [workbench._models.itemText(i) for i in range(workbench._models.count())]
    assert any("Claude — Internet" in label for label in labels)
    assert any("On this Mac" in label for label in labels)

    index = next(i for i, label in enumerate(labels) if "Claude" in label)
    assert workbench._models.model().item(index).isEnabled() is False


def test_a_cloud_model_with_a_key_is_selectable(qt_app, project, configured_credentials):
    controller = AgentController(project, ScriptedProvider([]), Toolbox(project))
    workbench = Workbench(project, controller, None,
                          allow_cloud=True, credentials=configured_credentials)

    labels = [workbench._models.itemText(i) for i in range(workbench._models.count())]
    index = next(i for i, label in enumerate(labels) if "Claude" in label)
    assert workbench._models.model().item(index).isEnabled() is True


def test_the_status_line_says_which_kind_of_model_is_answering(qt_app, project):
    """Section 34: whether something needs the internet must always be visible."""
    local = ScriptedProvider([])
    controller = AgentController(project, local, Toolbox(project))
    workbench = Workbench(project, controller, None)
    assert workbench._status_name() == "Local AI"

    controller.use_provider(cloud_provider())
    assert workbench._status_name() == "Cloud AI"
