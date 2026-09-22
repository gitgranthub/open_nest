"""WORKORDER_01 section 30's "Show technical details" -- the Build / Preview panel.

The work order asks for errors in child-friendly language by default, with a control for
deeper troubleshooting. Until Phase 10 the whole of ``RunResult.failure_text`` went
straight into the panel, and that property's own docstring says it is "what the repair
loop needs to see" -- it is written for the model. HANDOFF section 6C left this for the
polish pass and noted that a compiler diagnostic is the case that most needs it.

The important constraint, and what most of this file pins: **``failure_text`` itself does
not change.** The repair loop, the honesty checks and the Arduino path all consume it, so
the only thing that moved is what the panel opens with.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.execution.python_runner import RunResult  # noqa: E402
from opennest.ui.workbench import (  # noqa: E402
    HIDE_DETAILS,
    SHOW_DETAILS,
    headline_failure,
)

TRACEBACK = """Traceback (most recent call last):
  File "/p/game.py", line 41, in <module>
    main()
  File "/p/game.py", line 22, in main
    player.move(player_x)
NameError: name 'player_x' is not defined"""

ARDUINO = """/p/src/project/project.ino: In function 'void loop()':
/p/src/project/project.ino:14:3: error: 'digitalWrit' was not declared in this scope
   digitalWrit(LED_BUILTIN, HIGH);
   ^~~~~~~~~~~
Error during build: exit status 1"""


def _failed(stderr: str, *, stdout: str = "", timed_out: bool = False) -> RunResult:
    return RunResult(
        exit_code=1, stdout=stdout, stderr=stderr, seconds=0.4, timed_out=timed_out
    )


# ------------------------------------------------------------ the headline

def test_a_python_error_leads_with_the_exception_not_the_call_stack():
    """The last line is the one that says what went wrong.

    Eight frames of call stack above it are exactly the "raw traceback" section 30 says
    not to open with.
    """
    headline = headline_failure(_failed(TRACEBACK))
    assert headline.startswith("NameError: name 'player_x' is not defined")
    assert "Traceback (most recent call last)" not in headline
    assert "player.move" not in headline


def test_a_compiler_error_leads_with_its_summary():
    """The same rule works for arduino-cli without knowing which tool produced it."""
    headline = headline_failure(_failed(ARDUINO))
    assert headline.startswith("Error during build: exit status 1")
    assert "digitalWrit(LED_BUILTIN, HIGH);" not in headline


def test_the_headline_says_how_much_it_is_not_showing():
    """Hiding detail silently would be worse than showing it. The count is the offer."""
    headline = headline_failure(_failed(TRACEBACK))
    assert "more lines of technical detail" in headline


def test_a_single_line_failure_gets_no_dangling_offer():
    headline = headline_failure(_failed("PermissionError: [Errno 13] denied"))
    assert headline == "PermissionError: [Errno 13] denied"
    assert "more lines" not in headline


def test_a_timeout_is_reported_as_a_timeout():
    """There is no error line for this case, so the raw text says nothing actionable."""
    run = RunResult(
        exit_code=None, stdout="", stderr="", seconds=30.0, timed_out=True
    )
    headline = headline_failure(run)
    assert "still running after 30 seconds" in headline


def test_a_silent_failure_says_that_rather_than_nothing():
    run = _failed("")
    assert headline_failure(run) == "It stopped, and said nothing about why."


def test_the_headline_never_invents_an_explanation():
    """It selects a line that is already there; it does not paraphrase.

    Explaining the error is the assistant's job, in the conversation. A second, dumber
    account of the same failure in the panel could be wrong, and being wrong about why a
    child's project broke is worse than being terse.
    """
    headline = headline_failure(_failed(TRACEBACK))
    assert headline.splitlines()[0] in TRACEBACK


# ------------------------------------------------------------ failure_text is untouched

def test_the_repair_loop_still_sees_everything():
    """``failure_text`` is consumed by the repair loop and must not have been trimmed."""
    run = _failed(TRACEBACK, stdout="score 0\nscore 1")
    detail = run.failure_text
    assert "Traceback (most recent call last)" in detail
    assert "NameError: name 'player_x' is not defined" in detail
    assert "Output before it stopped:" in detail
    assert "score 1" in detail


def test_the_headline_is_derived_from_failure_text_not_a_second_capture():
    """One source of truth for what happened, presented two ways."""
    run = _failed(ARDUINO)
    assert headline_failure(run).splitlines()[0] in run.failure_text


# ------------------------------------------------------------ the toggle

@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def bench(qt_app, tmp_path):
    from opennest.agent.controller import AgentController
    from opennest.agent.tools import Toolbox
    from opennest.ai.provider import Reply
    from opennest.projects.manager import create_project
    from opennest.ui.workbench import Workbench
    from tests.conftest import ScriptedProvider

    project = create_project("Asteroid Game", "games", root=tmp_path / "projects")
    provider = ScriptedProvider([Reply(text="ok")] * 2)
    widget = Workbench(project, AgentController(project, provider, Toolbox(project)))
    widget.resize(1180, 760)
    widget.show()
    yield widget
    if widget._thread is not None:
        widget._thread.quit()
        widget._thread.wait(5000)
    widget.close()


class _Result:
    """What ``_show_run`` is handed. Only ``.run`` is read on this path."""

    def __init__(self, run):
        self.run = run


def test_the_panel_opens_with_the_headline_and_offers_the_rest(bench):
    """The defect: the panel used to open with the whole traceback."""
    bench._show_run(_Result(_failed(TRACEBACK)))

    shown = bench._output.toPlainText()
    assert "NameError: name 'player_x' is not defined" in shown
    assert "Traceback (most recent call last)" not in shown, "opened with the raw stack"
    assert not bench._details_button.isHidden()
    assert bench._details_button.text() == SHOW_DETAILS


def test_the_toggle_reveals_the_exact_output_and_puts_it_back(bench):
    bench._show_run(_Result(_failed(TRACEBACK)))

    bench._toggle_details()
    revealed = bench._output.toPlainText()
    assert "Traceback (most recent call last)" in revealed
    assert 'File "/p/game.py", line 41, in <module>' in revealed
    assert bench._details_button.text() == HIDE_DETAILS

    bench._toggle_details()
    assert "Traceback (most recent call last)" not in bench._output.toPlainText()
    assert bench._details_button.text() == SHOW_DETAILS


def test_a_successful_run_offers_no_details(bench):
    """Nothing to troubleshoot, so nothing to offer."""
    ok = RunResult(
        exit_code=0, stdout="score 12", stderr="", seconds=0.2, timed_out=False
    )
    bench._show_run(_Result(ok))

    assert bench._output.toPlainText() == "score 12"
    assert bench._details_button.isHidden()


def test_the_button_does_not_linger_over_unrelated_panel_content(bench):
    """A stale toggle holding some earlier run's stderr would be its own small lie.

    Everything that is not a failure goes through ``_panel_text``, which clears the
    detail, so opening a file after a failed run cannot leave the button behind.
    """
    bench._show_run(_Result(_failed(TRACEBACK)))
    assert not bench._details_button.isHidden()

    bench._panel_text("src/game.py\n\nprint('hello')")
    assert bench._details_button.isHidden()
    assert bench._technical_detail == ""

    bench._toggle_details()  # must not resurrect the old traceback
    assert "Traceback" not in bench._output.toPlainText()


def test_a_second_failure_replaces_the_first(bench):
    bench._show_run(_Result(_failed(TRACEBACK)))
    bench._toggle_details()
    assert "NameError" in bench._output.toPlainText()

    bench._show_run(_Result(_failed(ARDUINO)))
    shown = bench._output.toPlainText()
    assert "Error during build" in shown
    assert "NameError" not in shown, "still showing the previous run"
    assert bench._details_button.text() == SHOW_DETAILS, "left expanded from last time"


def test_the_control_is_named_the_way_the_work_order_names_it():
    assert SHOW_DETAILS == "Show technical details"
    assert HIDE_DETAILS == "Hide technical details"
