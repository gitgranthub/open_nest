"""Workbench behaviour that is logic rather than appearance.

PLAN.md section 6 puts UI behaviour on a manual checklist, and that is still right for
how the thing *looks*. But Phase 5 put real decisions in this widget -- which panel a
file was dropped on, which directory it lands in, what goes with the next message -- and
those regress silently. So they get a headless test; nothing here asserts on pixels,
fonts, or layout.

Runs under Qt's ``offscreen`` platform, so it needs no display and stays as hermetic as
the rest of the suite. It skips rather than fails if that platform is unavailable.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import Reply  # noqa: E402
from opennest.assets import kinds  # noqa: E402
from opennest.assets import manager as assets  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402
from tests.test_assets import SPACESHIP  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - PySide6 is an application dependency
        pytest.skip("PySide6 is not installed")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def bench(qt_app, project):
    from opennest.ui.workbench import Workbench

    provider = ScriptedProvider([Reply(text="ok")] * 4)
    controller = AgentController(project, provider, Toolbox(project))
    widget = Workbench(project, controller)
    widget.resize(1180, 760)
    widget.show()
    yield widget
    # A live worker thread outliving its widget crashes the interpreter rather than
    # failing a test, which is a confusing way to find out about it.
    if widget._thread is not None:
        widget._thread.quit()
        widget._thread.wait(5000)
    widget.close()


@pytest.fixture
def picture(tmp_path):
    source = tmp_path / "dragged" / "spaceship.png"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(SPACESHIP)
    return source


def items(widget):
    return [widget.item(i).text() for i in range(widget.count())]


def answer_with(bench, role):
    """Skip the modal classification dialog and answer it with ``role``."""
    bench._ask_what_it_is = lambda source: role


def test_files_and_assets_are_listed_separately(bench, picture) -> None:
    """Section 14 and DESIGN_DOC both show the project's code and its assets apart."""
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=False)

    assert "src/game.py" in items(bench._files)
    assert items(bench._assets) == ["spaceship.png"]
    # The asset is not also repeated in the file list.
    assert "assets/spaceship.png" not in items(bench._files)


def test_the_classification_chosen_decides_where_it_lands(bench, picture) -> None:
    answer_with(bench, kinds.REFERENCE)
    bench._add([picture], attach=False)
    assert (bench.project.directory / "docs" / "spaceship.png").is_file()
    assert not (bench.project.directory / "assets" / "spaceship.png").exists()


def test_cancelling_the_dialog_imports_nothing(bench, picture) -> None:
    bench._ask_what_it_is = lambda source: None
    bench._add([picture], attach=False)
    assert items(bench._assets) == []


def test_a_drop_on_the_chat_goes_with_the_next_message(bench, picture) -> None:
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=True)

    assert [a.name for a in bench._pending] == ["spaceship.png"]
    assert "spaceship.png" in bench._attached_label.text()
    assert bench._attached_label.isVisible()


def test_a_drop_on_the_file_panel_does_not(bench, picture) -> None:
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=False)

    assert bench._pending == []
    assert not bench._attached_label.isVisible()
    # It is still in the project -- it was imported, just not attached to a message.
    assert items(bench._assets) == ["spaceship.png"]


def test_where_the_file_landed_decides_whether_it_is_attached(bench) -> None:
    """The rule behind the two tests above, checked against the real panel geometry."""
    chat = bench._chat_panel.geometry().center()
    files = bench._assets_panel.geometry().center()
    assert bench.is_chat_position(chat)
    assert not bench.is_chat_position(files)


def test_sending_hands_the_attachment_over_and_clears_it(bench, picture, monkeypatch) -> None:
    """What the worker is given, and that the chip is emptied.

    The real worker thread is not started: this is about what ``_send`` hands over, and
    a live QThread in a test buys nothing but flakiness. The turn itself is covered by
    tests/test_assets.py against the controller directly.
    """
    from PySide6.QtCore import QThread

    started = []

    def capture(parent, worker):
        started.append(worker)
        return QThread(parent)  # a real thread object, deliberately never started

    monkeypatch.setattr("opennest.ui.workbench.run_in_thread", capture)
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=True)

    bench._input.setText("Use this picture for my spaceship.")
    bench._send()

    assert len(started) == 1
    assert started[0].text == "Use this picture for my spaceship."
    assert [a.path for a in started[0].attachments] == ["assets/spaceship.png"]
    assert bench._pending == []
    assert not bench._attached_label.isVisible()
    # The child sees what went with the message, not just the words.
    assert "[ spaceship.png ]" in bench._transcript.toPlainText()


def test_the_model_is_told_about_the_import_straight_away(bench, picture) -> None:
    """Without this the assistant does not know the file exists until something else
    refreshes the prompt."""
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=False)
    assert "assets/spaceship.png" in bench.controller.history[0].content


def test_a_refused_import_does_not_break_the_workbench(bench, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(assets, "MAX_IMPORT_BYTES", 10)
    huge = tmp_path / "huge.csv"
    huge.write_text("x" * 100)
    answer_with(bench, kinds.DATASET)

    warned = []
    monkeypatch.setattr(
        "opennest.ui.workbench.QMessageBox.warning",
        lambda *args, **kwargs: warned.append(args[-1]),
    )
    bench._add([huge], attach=False)

    assert warned and "too big" in warned[0]
    assert items(bench._assets) == []


def test_double_clicking_an_asset_shows_what_is_known_about_it(bench, picture) -> None:
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=False)
    bench._describe_asset(bench._assets.item(0))

    shown = bench._output.toPlainText()
    assert "assets/spaceship.png" in shown
    assert "64x64 pixels" in shown
