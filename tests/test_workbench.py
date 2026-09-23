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


# -- Phase 7: the main button, charts, boards and pictures --------------------


def _bench_for(qt_app, project, **kwargs):
    from opennest.ui.workbench import Workbench

    provider = ScriptedProvider([Reply(text="ok")] * 4)
    controller = AgentController(project, provider, Toolbox(project))
    widget = Workbench(project, controller, **kwargs)
    widget.resize(1180, 760)
    return widget


def test_compile_no_longer_shows_a_child_a_message_meant_for_the_model(
    qt_app, tmp_path, monkeypatch
) -> None:
    """The bug this phase found by pressing the button.

    ``_run`` always dispatched ``run_project``. Arduino has no run command and no such
    tool, so the Toolbox refused it with text written for a model -- "'run_project' is
    not available here. You can use: read_file, edit_file, write_file, compile_project."
    -- and that went straight into the child's Build / Preview panel.
    """
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: False)
    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    bench = _bench_for(qt_app, sketch)
    try:
        bench._run()
        shown = bench._output.toPlainText()
        assert "run_project" not in shown
        assert "is not available here" not in shown
        assert "not installed" in shown
    finally:
        bench.close()


def test_a_compiling_profile_gets_a_tick_and_no_stop_button(
    qt_app, tmp_path, monkeypatch
) -> None:
    """WORKORDER_01 section 30 shows "✓ Compile", not "▶ Compile"."""
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: False)
    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    bench = _bench_for(qt_app, sketch)
    try:
        assert bench._run_button.text().startswith("✓")
        assert "Compile" in bench._run_button.text()
        # Nothing is left running by a compile, so there is nothing to stop.
        # isVisibleTo, not isVisible: this widget was never shown, so isVisible is
        # False for everything and would pass whatever the code did.
        assert not bench._stop_button.isVisibleTo(bench)
    finally:
        bench.close()


def test_a_game_keeps_its_play_arrow(bench) -> None:
    assert bench._run_button.text().startswith("▶")


def test_the_board_picker_says_why_it_is_empty_without_the_tools(
    qt_app, tmp_path, monkeypatch
) -> None:
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: False)
    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    bench = _bench_for(qt_app, sketch)
    try:
        assert "not installed" in bench._board.currentText()
        assert not bench._board.isEnabled()
        assert not bench._upload_button.isEnabled()
    finally:
        bench.close()


def test_the_board_picker_offers_no_preselected_board(
    qt_app, tmp_path, monkeypatch
) -> None:
    """Section 8: choosing a board for them chooses every pin on it."""
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: True)
    monkeypatch.setattr(
        arduino, "boards",
        lambda: [arduino.Board("Arduino UNO", "arduino:avr:uno")],
    )
    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    bench = _bench_for(qt_app, sketch)
    try:
        assert bench._board.currentData() is None
        assert "Choose" in bench._board.currentText()
        # Upload cannot happen until a board is known.
        assert not bench._upload_button.isEnabled()
    finally:
        bench.close()


def test_picking_a_board_remembers_it_on_the_project(
    qt_app, tmp_path, monkeypatch
) -> None:
    from opennest.execution import arduino
    from opennest.projects.manager import create_project, open_project

    monkeypatch.setattr(arduino, "available", lambda: True)
    monkeypatch.setattr(
        arduino, "boards",
        lambda: [arduino.Board("Arduino UNO", "arduino:avr:uno")],
    )
    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    bench = _bench_for(qt_app, sketch)
    try:
        bench._board.setCurrentIndex(bench._board.findData("arduino:avr:uno"))
        assert sketch.manifest.arduino_board == "arduino:avr:uno"
        assert open_project(sketch.directory).manifest.arduino_board == "arduino:avr:uno"
        assert bench._upload_button.isEnabled()
    finally:
        bench.close()


def test_upload_is_refused_when_a_parent_has_not_allowed_it(
    qt_app, tmp_path, monkeypatch
) -> None:
    """Unanswered means no. The gate is consulted before anything is sent."""
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: True)
    monkeypatch.setattr(arduino, "boards", lambda: [])
    monkeypatch.setattr(
        arduino, "connected_ports",
        lambda: [arduino.Port("/dev/cu.usbmodem1101",
                              arduino.Board("Arduino UNO", "arduino:avr:uno"))],
    )
    sent = []
    monkeypatch.setattr(arduino, "upload", lambda *a, **k: sent.append(a))

    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    sketch.manifest.arduino_board = "arduino:avr:uno"
    bench = _bench_for(qt_app, sketch, upload_policy=lambda: False)
    try:
        bench._upload()
        assert not sent, "sent a sketch to a board without permission"
        assert "not allowed" in bench._output.toPlainText()
    finally:
        bench.close()


def test_upload_proceeds_once_a_parent_allows_it(qt_app, tmp_path, monkeypatch) -> None:
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: True)
    monkeypatch.setattr(arduino, "boards", lambda: [])
    monkeypatch.setattr(
        arduino, "connected_ports",
        lambda: [arduino.Port("/dev/cu.usbmodem1101",
                              arduino.Board("Arduino UNO", "arduino:avr:uno"))],
    )
    calls = []

    class FakeRun:
        ok = True
        stdout = "done"
        failure_text = ""

    def fake_upload(project, fqbn, port):
        calls.append((fqbn, port))
        return FakeRun()

    monkeypatch.setattr(arduino, "upload", fake_upload)

    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    sketch.manifest.arduino_board = "arduino:avr:uno"
    bench = _bench_for(qt_app, sketch, upload_policy=lambda: True)
    try:
        bench._upload()
        assert calls == [("arduino:avr:uno", "/dev/cu.usbmodem1101")]
    finally:
        bench.close()


def test_upload_with_nothing_plugged_in_says_so(qt_app, tmp_path, monkeypatch) -> None:
    from opennest.execution import arduino
    from opennest.projects.manager import create_project

    monkeypatch.setattr(arduino, "available", lambda: True)
    monkeypatch.setattr(arduino, "boards", lambda: [])
    monkeypatch.setattr(arduino, "connected_ports", lambda: [])
    sent = []
    monkeypatch.setattr(arduino, "upload", lambda *a, **k: sent.append(a))

    sketch = create_project("Traffic Light", "arduino", root=tmp_path)
    sketch.manifest.arduino_board = "arduino:avr:uno"
    bench = _bench_for(qt_app, sketch, upload_policy=lambda: True)
    try:
        bench._upload()
        assert not sent
        assert "USB" in bench._output.toPlainText()
    finally:
        bench.close()


def test_a_chart_a_run_produced_is_put_on_screen(bench) -> None:
    """DoD 34. A chart nobody can see is not a result."""
    from tests.test_assets import SPACESHIP

    assert not bench._chart.isVisible()
    bench._note_images()
    charts = bench.project.directory / "charts"
    charts.mkdir(exist_ok=True)
    (charts / "chart.png").write_bytes(SPACESHIP)

    bench._show_any_chart()

    assert bench._chart.isVisible()
    assert bench._chart.pixmap() is not None
    assert not bench._chart.pixmap().isNull()
    assert "charts/chart.png" in bench._chart_caption.text()


def test_no_chart_appears_when_a_run_produced_none(bench, picture) -> None:
    """A picture the child imported is not this run's output."""
    answer_with(bench, kinds.ASSET)
    bench._add([picture], attach=False)
    bench._note_images()

    bench._show_any_chart()

    assert not bench._chart.isVisible()


def test_a_starter_idea_is_offered_not_sent(qt_app, project) -> None:
    """Sections 5 and 27: an idea card seeds the first message.

    Filled in rather than sent, because a child who picked "Maze" usually wants to add
    something before anything is built.
    """
    bench = _bench_for(qt_app, project, starter_idea="Maze")
    try:
        assert "maze" in bench._input.text().lower()
        # Nothing has been said to the model yet.
        assert bench._transcript.toPlainText() == ""
        assert bench._thread is None
    finally:
        bench.close()


def test_making_a_picture_with_cloud_off_explains_rather_than_failing(
    qt_app, tmp_path, credentials
) -> None:
    from opennest.projects.manager import create_project

    pictures = create_project("My Pictures", "image_creation", root=tmp_path)
    bench = _bench_for(qt_app, pictures, allow_cloud=False, credentials=credentials)
    try:
        bench._run()
        shown = bench._output.toPlainText()
        assert "turned off" in shown
        assert bench._thread is None, "started generating with cloud off"
    finally:
        bench.close()


def test_making_a_picture_with_no_key_points_at_the_key(
    qt_app, tmp_path, credentials
) -> None:
    from opennest.projects.manager import create_project

    pictures = create_project("My Pictures", "image_creation", root=tmp_path)
    bench = _bench_for(qt_app, pictures, allow_cloud=True, credentials=credentials)
    try:
        bench._run()
        assert "key" in bench._output.toPlainText().lower()
        assert bench._thread is None
    finally:
        bench.close()


def test_a_game_keeps_its_stop_button(bench) -> None:
    """The companion to the compile case, so the assertion above means something."""
    assert bench._stop_button.isVisibleTo(bench)


def test_a_generated_picture_is_shown_without_guessing_which_file_it_was(
    qt_app, tmp_path, configured_credentials
) -> None:
    """The application put the file there, so it does not need to search for it.

    The run path compares the project before and after because the model cannot be
    trusted to report a path. Generation is the opposite case: Open Nest saved the file
    itself and knows exactly which one it is.
    """
    from opennest.projects.manager import create_project
    from tests.test_images import PNG, ScriptedTransport, png_payload

    pictures = create_project("My Pictures", "image_creation", root=tmp_path)
    bench = _bench_for(qt_app, pictures, allow_cloud=True, credentials=configured_credentials)
    bench.show()
    try:
        from opennest.ai import images

        asset = images.generate_into(
            pictures, "a rocket",
            credentials=configured_credentials, transport=ScriptedTransport(png_payload(PNG)),
        )
        bench._image_ready(asset)

        assert bench._chart.isVisible()
        assert asset.path in bench._chart_caption.text()
        # And the honesty line is said where the child will read it.
        transcript = bench._transcript.toPlainText()
        assert "Nothing has looked at the picture" in transcript
    finally:
        bench.close()


# ------------------------------------------------- About Gary (the optional aside)

def test_the_about_affordance_is_labelled_plainly(bench) -> None:
    """It carries no text, so it needs an ordinary accessible name (guide section 46).

    "About Gary" rather than anything clever: the glyph is a hint, and the label is how
    it is reachable at all for someone not using a mouse and eyes.
    """
    from opennest.ui import about_gary

    button = bench._about_gary
    assert button.accessibleName() == about_gary.TITLE == "About Gary"
    assert button.toolTip() == about_gary.TITLE
    assert button.text() == about_gary.GLYPH


def test_nothing_opens_the_bio_on_its_own(bench, qt_app) -> None:
    """The developer's constraint: it appears only if someone gets curious.

    Not onboarding, not a first-run card, not a tooltip that fires on hover. Building
    the Workbench must leave no popover anywhere.
    """
    from opennest.ui.about_gary import AboutPopover

    qt_app.processEvents()
    assert not bench.findChildren(AboutPopover)
    assert not [w for w in qt_app.topLevelWidgets() if isinstance(w, AboutPopover)]


def test_clicking_it_opens_a_popover_and_not_a_dialog(bench, qt_app) -> None:
    """A modal window would make reading a joke feel like a task.

    ``Qt.Popup`` is the difference: it dismisses on the next click anywhere and blocks
    nothing behind it, which is what an information glyph should do.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog

    from opennest.ui.about_gary import AboutPopover

    bench._about_gary.click()
    qt_app.processEvents()
    popovers = [w for w in qt_app.topLevelWidgets() if isinstance(w, AboutPopover)]
    try:
        assert len(popovers) == 1
        popover = popovers[0]
        assert not isinstance(popover, QDialog), "a dialog would block the interface"
        assert popover.windowFlags() & Qt.WindowType.Popup
        assert not popover.isModal()
    finally:
        for popover in popovers:
            popover.close()
            popover.deleteLater()


def test_the_popover_actually_carries_the_bio(bench, qt_app) -> None:
    """Including the last line, which is the reason the thing exists."""
    from PySide6.QtWidgets import QLabel

    from opennest.ui.about_gary import AboutPopover

    bench._about_gary.click()
    qt_app.processEvents()
    popovers = [w for w in qt_app.topLevelWidgets() if isinstance(w, AboutPopover)]
    try:
        shown = " ".join(label.text() for label in popovers[0].findChildren(QLabel))
        assert "About Gary" in shown
        assert "expressive dance" in shown
        assert "Gary wrote this bio." in shown
        # No artwork was borrowed to illustrate him (guide section 47).
        assert not [
            label for label in popovers[0].findChildren(QLabel)
            if label.pixmap() is not None and not label.pixmap().isNull()
        ]
    finally:
        for popover in popovers:
            popover.close()
            popover.deleteLater()


def test_the_popover_is_tall_enough_for_the_whole_bio(qt_app) -> None:
    """A regression found by rendering it, not by any assertion.

    A wrapped ``QLabel`` reports a single-line ``sizeHint`` until its width is
    constrained, so ``adjustSize`` sized the popover for one line: the first paragraph
    rendered behind the heading and the last one -- "Gary wrote this bio.", the entire
    reason the popover exists -- was cut off below the border. Nothing failed; the
    window was simply too short.
    """
    from opennest.ui.about_gary import AboutPopover

    popover = AboutPopover()
    try:
        popover.adjustSize()
        needed = popover.body.heightForWidth(popover.body.width())
        assert popover.body.height() >= needed, (
            f"the bio needs {needed}px and has {popover.body.height()}px -- the last "
            "line is being clipped"
        )
        assert popover.height() >= needed, "the popover is shorter than its own text"
    finally:
        popover.deleteLater()


# --------------------------------------------------- Phase 11: starters and the website

@pytest.fixture
def make_bench(qt_app, tmp_path):
    """A Workbench for any profile and any starter choice, cleaned up afterwards."""
    from opennest.projects.manager import create_project
    from opennest.ui.workbench import Workbench

    made = []

    def build(profile_id: str, *, starter_id=..., name="Test Project"):
        from opennest.projects.manager import PROFILE_DEFAULT

        project = create_project(
            name, profile_id,
            starter_id=PROFILE_DEFAULT if starter_id is ... else starter_id,
            root=tmp_path,
        )
        provider = ScriptedProvider([Reply(text="ok")] * 4)
        widget = Workbench(project, AgentController(project, provider, Toolbox(project)))
        widget.resize(1180, 760)
        widget.show()
        made.append(widget)
        return widget

    yield build
    for widget in made:
        if widget._thread is not None:
            widget._thread.quit()
            widget._thread.wait(5000)
        # What MainWindow._close_project does, for the same reason: closing a parent
        # does not call closeEvent on its children, and a live web page outliving its
        # profile is a crash rather than a warning.
        widget.release()
        widget.close()


def test_the_starter_offer_appears_only_in_an_empty_project(make_bench) -> None:
    """Section 9. The offer is one click precisely because it cannot reach any work."""
    empty = make_bench("website", starter_id=None)
    assert empty._starter_buttons
    assert all(not b.isHidden() for b in empty._starter_buttons)
    assert not empty._empty_note.isHidden()

    full = make_bench("website", name="Has Files")
    assert all(b.isHidden() for b in full._starter_buttons)
    assert full._empty_note.isHidden()


def test_a_blank_project_is_told_it_is_empty_without_being_offered_a_starter(
    make_bench,
) -> None:
    """Blank has no kit, so the empty state says what to do instead of offering one."""
    bench = make_bench("blank")
    assert bench._starter_buttons == []
    assert not bench._empty_note.isHidden()
    assert "Gary" in bench._empty_note.text()


def test_adding_a_starter_fills_the_project_and_retires_the_offer(make_bench) -> None:
    bench = make_bench("website", starter_id=None)
    bench._add_starter("website_basic")

    assert (bench.project.directory / "src" / "index.html").is_file()
    assert bench.project.manifest.starter_id == "website_basic"
    assert all(b.isHidden() for b in bench._starter_buttons)
    # And the model was told, rather than finding out on its next turn.
    assert "Basic Website" in bench.controller.history[0].content


def test_pressing_run_on_an_empty_project_explains_itself(make_bench) -> None:
    """Starting empty is supported, so its first press of Run is answered like it."""
    bench = make_bench("blank")
    bench._run()
    said = bench._output.toPlainText()
    assert "nothing to run yet" in said.lower()
    assert "src/main.py" in said
    # Never the interpreter's own message about a path the child did not choose.
    assert "No such file or directory" not in said


def test_a_website_workbench_has_a_page_and_a_game_does_not(make_bench) -> None:
    assert make_bench("website")._web is not None
    assert make_bench("games", name="A Game")._web is None


def test_previewing_an_empty_website_explains_instead_of_rendering(make_bench) -> None:
    bench = make_bench("website", starter_id=None)
    bench._run()
    assert "nothing to run yet" in bench._output.toPlainText().lower()


def test_previewing_a_page_that_wants_the_internet_says_so_first(make_bench) -> None:
    """Chromium drops the request silently, so the warning cannot wait for the render."""
    bench = make_bench("website")
    (bench.project.directory / "src" / "index.html").write_text(
        '<img src="https://example.com/cat.gif" alt="">', encoding="utf-8"
    )
    from opennest.execution import web_preview

    shown = []
    bench._web.show_page = lambda url: shown.append(url) or True
    bench._run()

    assert shown, "the page was not shown"
    assert "example.com" in bench._output.toPlainText()
    assert web_preview.remote_references(bench.project)


def test_the_file_panel_does_not_show_open_nests_own_bookkeeping(make_bench) -> None:
    """Found by looking at the render, which is the only way it could have been.

    A project started empty listed ``project.json`` directly above the words "Nothing
    here yet." The manifest was always in that panel and always read as a file the child
    had made; the empty state turned it into a contradiction on screen while every test
    passed.
    """
    bench = make_bench("website", starter_id=None)
    assert items(bench._files) == []

    full = make_bench("website", name="Has Files")
    listed = items(full._files)
    assert "project.json" not in listed
    assert "src/index.html" in listed, listed


def test_the_model_is_still_told_what_is_really_in_the_project(make_bench) -> None:
    """The panel hides the manifest from a child. The prompt must not hide it from Gary."""
    from opennest.security.sandbox import visible_files

    bench = make_bench("website", name="Real Files")
    assert "project.json" in visible_files(bench.project.directory)


# ----------------------------------------------- the game window's lifetime

def test_closing_a_project_stops_a_game_that_is_still_running(bench, monkeypatch) -> None:
    """Otherwise the window outlives the Workbench and nothing owns it any more.

    Found in the Phase 12 test drive, watching it happen: Run Game opens a window in
    another process -- that is the security boundary, a game is not run inside the
    application -- and Stop lived on the Workbench. Once the project closed there was
    no control left for it, so the only way to be rid of the game was to quit the game
    itself.

    Deliberately *not* accompanied by a test about where the window opens. SDL already
    centres it on macOS (measured: a 640x480 window landed at 544,318 on a 1728x1117
    screen, identical with and without SDL_VIDEO_CENTERED), so there was nothing to
    fix there -- and positioning it over the Build / Preview panel to look docked was
    tried and withdrawn, because Open Nest can place another process's window but
    cannot clip it. See SPIKES.md section 20I.
    """
    from opennest.execution.python_runner import RunResult

    stopped: list = []
    monkeypatch.setattr(
        "opennest.ui.workbench.stop_project", lambda run: stopped.append(run)
    )
    running = RunResult(None, "", "", 0.1, False, still_running=True)
    bench.toolbox.last_run = running

    bench.release()
    assert stopped == [running], "closing the project left the game running"


def test_releasing_a_project_that_never_ran_anything_is_harmless(bench) -> None:
    bench.toolbox.last_run = None
    bench.release()


# ------------------------------------------------------ saving a version by hand

def test_a_child_can_save_a_version_on_purpose(bench, monkeypatch) -> None:
    """Section 29A saves automatically, and that is not the whole story.

    Somebody who has just got a chart looking right wants to *mark* that, not trust
    that something did. The machinery already existed -- ``VersionHistory.save`` --
    and Undo was the only thing exposing any of it.
    """
    saved: list = []

    class Versions:
        can_undo = True

        def save(self, label):
            saved.append(label)
            return "abc123"

    bench.versions = Versions()
    bench._save_button.setEnabled(True)
    bench._save_button.click()

    from opennest.versioning.checkpoint import LABEL_SAVED_BY_HAND

    assert saved == [LABEL_SAVED_BY_HAND]
    assert "Saved" in bench._transcript.toPlainText()


def test_saving_when_nothing_changed_says_so_rather_than_lying(bench) -> None:
    """Autosave has usually taken it already, and an identical second version is noise."""

    class Versions:
        can_undo = True

        def save(self, label):
            return None          # git_manager.commit: nothing to commit

    bench.versions = Versions()
    bench._save_button.setEnabled(True)
    bench._save_button.click()

    said = bench._transcript.toPlainText()
    assert "nothing new to save" in said, said


def test_a_blocked_credential_stops_a_manual_save_visibly(bench, monkeypatch) -> None:
    """The one failure that must surface: silently not saving would be worse."""
    from opennest.versioning.git_manager import SecretsFound
    from opennest.versioning.secret_scanner import Finding

    warned: list = []
    monkeypatch.setattr(
        "opennest.ui.workbench.QMessageBox.warning",
        lambda *args, **kwargs: warned.append(args[-1]),
    )

    findings = [Finding(path="src/analysis.py", line=3, description="an API key")]

    class Versions:
        can_undo = True

        def save(self, label):
            raise SecretsFound(findings)

    bench.versions = Versions()
    bench._save_button.setEnabled(True)
    bench._save_button.click()
    assert warned and "API key" in warned[0]
