"""The game drawn in the Workbench: the widget, and how the Workbench looks after it.

Phase 13. Offscreen Qt, like the rest of the Workbench tests, with a stand-in stream for
everything about behaviour and one real game -- run through the real Run Game button, its
worker thread and the real sandbox -- because a test that reaches behaviour through an
inline seam says nothing about the thread (PHASE_12_HANDOFF section 3).
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController, Turn  # noqa: E402
from opennest.agent.tools import Step, Toolbox  # noqa: E402
from opennest.ai.provider import Reply  # noqa: E402
from opennest.execution.live_view import Frame  # noqa: E402
from opennest.execution.python_runner import RunResult  # noqa: E402
from opennest.security.process_sandbox import sandbox_available  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

needs_sandbox = pytest.mark.skipif(
    not sandbox_available(), reason="the process sandbox cannot be applied here"
)


class FakeStream:
    """What a game view reads from a stream, and a record of what it sent back."""

    def __init__(self, width=64, height=48):
        self.frame = Frame(1, width, height, b"\x10\x20\x30\xff" * (width * height))
        self.title = "Eagle Patrol"
        self.finished = False
        self.broken = ""
        self.sent: list = []

    def latest(self):
        return self.frame

    def send_key(self, name, down, text=""):
        self.sent.append(("key", name, down))

    def send_mouse(self, kind, x, y, button=0):
        self.sent.append(("mouse", kind, x, y, button))

    def release_all(self):
        self.sent.append(("release",))

    def close(self):
        self.finished = True


class FakeOutput:
    def __init__(self):
        self.stopped = False


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def live_run(stream=None, process=None):
    return RunResult(None, "", "", 0.1, False, still_running=True,
                     process=process or FakeProcess(), output=FakeOutput(),
                     live=stream or FakeStream())


class _Result:
    def __init__(self, run):
        self.run, self.ok, self.content = run, run.ok, ""


def pump(seconds: float, until=None) -> bool:
    """A nested event loop, never ``qWait`` -- which starves worker threads of the GIL."""
    from PySide6.QtCore import QEventLoop, QTimer

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
        if until is not None and until():
            return True
    return until() if until is not None else True


# ------------------------------------------------------------ the pure parts

def test_a_picture_is_fitted_whole_and_centred(qt_app) -> None:
    from PySide6.QtCore import QRectF

    from opennest.ui.game_view import fit

    target = fit(640, 480, QRectF(0, 0, 400, 400))
    assert (target.width(), target.height()) == (400, 300)
    assert (target.x(), target.y()) == (0, 50)
    assert fit(0, 480, QRectF(0, 0, 400, 400)).isEmpty()


def test_a_click_lands_in_the_games_own_pixels(qt_app) -> None:
    from PySide6.QtCore import QPointF, QRectF

    from opennest.ui.game_view import to_game

    target = QRectF(0, 50, 400, 300)          # a 640x480 game shown at 0.625
    assert to_game(QPointF(200, 200), target, 640, 480) == (320, 240)
    assert to_game(QPointF(0, 50), target, 640, 480) == (0, 0)
    assert to_game(QPointF(399.9, 349.9), target, 640, 480) == (639, 479)
    assert to_game(QPointF(200, 10), target, 640, 480) is None, "the letterbox is not the game"


def test_the_keys_a_game_hears_are_named_the_way_pygame_names_them(qt_app) -> None:
    from PySide6.QtCore import Qt

    from opennest.ui.game_view import pygame_key

    K = Qt.Key
    assert pygame_key(K.Key_Left) == "K_LEFT"
    assert pygame_key(K.Key_A) == "K_a" and pygame_key(K.Key_Z) == "K_z"
    assert pygame_key(K.Key_7) == "K_7"
    assert pygame_key(K.Key_Exclam) == "K_1", "a shifted symbol is the key it is on"
    assert pygame_key(K.Key_Space) == "K_SPACE"
    assert pygame_key(K.Key_Tab) is None, "Tab moves on to the next control"
    assert pygame_key(K.Key_Backtab) is None


# ------------------------------------------------------------ the widget

@pytest.fixture
def view(qt_app):
    """A game view beside a text box, in one active window -- focus needs both."""
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    from opennest.ui.game_view import GameView

    window = QWidget()
    layout = QVBoxLayout(window)
    widget = GameView()
    widget.chat = QLineEdit()
    layout.addWidget(widget)
    layout.addWidget(widget.chat)
    window.resize(360, 320)
    window.show()
    window.activateWindow()
    pump(0.05)
    yield widget
    widget.detach()
    window.close()


def test_the_newest_picture_is_what_is_painted(view) -> None:
    stream = FakeStream()
    view.attach(stream)
    assert view.current_frame() is stream.frame
    stream.frame = Frame(2, 64, 48, b"\xff\xff\xff\xff" * (64 * 48))
    pump(0.1)
    assert view.current_frame().sequence == 2
    assert not view.grab().isNull()


def test_a_held_key_is_one_press_and_one_release(view) -> None:
    """Qt repeats a held key as press/release pairs; the game must see it held."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication

    stream = FakeStream()
    view.attach(stream)
    view.setFocus()
    for kind, repeat in ((QEvent.Type.KeyPress, False), (QEvent.Type.KeyRelease, True),
                         (QEvent.Type.KeyPress, True), (QEvent.Type.KeyRelease, False)):
        QApplication.sendEvent(view, QKeyEvent(kind, Qt.Key.Key_Right,
                                               Qt.KeyboardModifier.NoModifier, "", repeat))
    assert [s for s in stream.sent if s[0] == "key"] == [
        ("key", "K_RIGHT", True), ("key", "K_RIGHT", False)]


def test_letting_go_of_the_game_lets_go_of_its_keys(view) -> None:
    """Otherwise an arrow held while the child clicked the chat stays held for ever."""
    stream = FakeStream()
    view.attach(stream)
    view.setFocus()
    pump(0.05)
    assert view.hasFocus(), "fixture is wrong: the game never had the keyboard"
    view.chat.setFocus()
    pump(0.05)
    assert ("release",) in stream.sent


def test_a_click_becomes_a_click_in_the_game(view) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest

    stream = FakeStream(width=320, height=240)
    view.attach(stream)
    QTest.mouseClick(view, Qt.MouseButton.LeftButton, pos=view.rect().center())
    clicks = [s for s in stream.sent if s[0] == "mouse" and s[1] in ("down", "up")]
    assert [c[1] for c in clicks] == ["down", "up"] and all(c[4] == 1 for c in clicks)
    assert view.hasFocus(), "clicking the game is how it hears the keyboard"
    _ = QPointF


def test_tab_leaves_the_game_rather_than_being_sent_to_it(view) -> None:
    """The Workbench had a keyboard trap once (SPIKES.md section 20F)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    stream = FakeStream()
    view.attach(stream)
    view.setFocus()
    pump(0.05)
    QTest.keyClick(view, Qt.Key.Key_Tab)
    pump(0.05)
    assert view.chat.hasFocus(), "Tab did not move on from the game"
    assert not [s for s in stream.sent if s[0] == "key"]


def test_a_stopped_game_hears_nothing_and_says_so(view) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    stream = FakeStream()
    view.attach(stream)
    view.show_stopped("Stopped")
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert not [s for s in stream.sent if s[0] == "key"]
    assert not view.running


def test_the_end_of_the_stream_is_announced_once(view) -> None:
    stream = FakeStream()
    ended = []
    view.ended.connect(lambda: ended.append(True))
    view.attach(stream)
    stream.finished = True
    pump(0.15)
    assert ended == [True]


def test_the_games_title_is_passed_on(view) -> None:
    titles = []
    view.title_changed.connect(titles.append)
    view.attach(FakeStream())
    assert titles == ["Eagle Patrol"]


# ------------------------------------------------------------ the Workbench

@pytest.fixture
def stops(monkeypatch):
    """Runs Open Nest was asked to stop. A real process is really stopped; a stand-in
    is recorded, so no test here kills something it only pretended to start."""
    import subprocess

    from opennest.execution import python_runner

    stopped = []

    def stop(run):
        if isinstance(run.process, subprocess.Popen):
            python_runner.stop_project(run)
            return
        stopped.append(run)
        if run.output is not None:
            run.output.stopped = True

    monkeypatch.setattr("opennest.ui.workbench.stop_project", stop)
    return stopped


@pytest.fixture
def game_bench(qt_app, project, stops):
    from opennest.ui.workbench import Workbench

    provider = ScriptedProvider([Reply(text="ok")] * 4)
    widget = Workbench(project, AgentController(project, provider, Toolbox(project)))
    widget.resize(1180, 760)
    widget.show()
    yield widget
    if widget._thread is not None:
        widget._thread.quit()
        widget._thread.wait(5000)
    widget.release()
    widget.close()


def test_only_a_games_workbench_has_a_game_view(game_bench, qt_app, tmp_path) -> None:
    """And Blank's, since the owner-test pass: a Blank project asked for a game is given
    one, and Run plays it here rather than in a window of its own (``plays_in_panel``)."""
    from opennest.projects.manager import create_project
    from opennest.ui.workbench import Workbench

    assert game_bench._game is not None and game_bench._game.isHidden()
    for profile in ("website", "research", "raspberry_pi", "arduino"):
        project = create_project(profile, profile, root=tmp_path)
        provider = ScriptedProvider([Reply(text="ok")])
        other = Workbench(project, AgentController(project, provider, Toolbox(project)))
        try:
            assert other._game is None, profile
        finally:
            other.release()
            other.close()


def test_a_running_game_is_shown_in_the_panel(game_bench) -> None:
    run = live_run()
    game_bench._show_run(_Result(run))
    assert game_bench._game.isVisibleTo(game_bench)
    assert game_bench._game.stream is run.live
    assert game_bench._stop_button.isEnabled()
    assert "running here" in game_bench._output.toPlainText()
    assert game_bench._game_title.text().startswith("Eagle Patrol")
    assert "click the game to play" in game_bench._game_title.text()


def test_the_game_is_shown_the_moment_it_starts(game_bench) -> None:
    """The ``playing`` step arrives before the four-second startup check has finished."""
    stream = FakeStream()
    game_bench._progress(Step("playing", "running the project", live=stream))
    assert game_bench._game.isVisibleTo(game_bench)
    assert game_bench._game.stream is stream
    assert "running the project" not in game_bench._transcript.toPlainText(), (
        "the tool step before it already said so"
    )


def test_a_crash_during_play_is_shown_and_gary_is_told(game_bench, monkeypatch) -> None:
    """Until Phase 13 nobody saw a crash after the startup check, Gary included."""
    crashed = RunResult(1, "", "Traceback ...\nZeroDivisionError: division by zero",
                        6.0, False)
    monkeypatch.setattr("opennest.ui.workbench.finished", lambda run: crashed)
    run = live_run(process=FakeProcess(returncode=1))
    game_bench.toolbox.last_run = run
    game_bench._show_run(_Result(run))
    run.live.finished = True
    game_bench._game_ended()

    assert "ZeroDivisionError" in game_bench._output.toPlainText()
    assert not game_bench._details_button.isHidden()
    assert game_bench.toolbox.last_run is crashed, "the next turn's facts still say running"
    assert not game_bench._stop_button.isEnabled()
    assert not game_bench._game.running


def test_a_game_the_child_stopped_did_not_fail(game_bench, monkeypatch) -> None:
    ended = RunResult(-15, "", "", 3.0, False)
    monkeypatch.setattr("opennest.ui.workbench.finished", lambda run: ended)
    run = live_run(process=FakeProcess(returncode=-15))
    run.output.stopped = True
    game_bench.toolbox.last_run = run
    game_bench._show_run(_Result(run))
    game_bench._game_ended()
    assert game_bench.toolbox.last_run is run
    assert "error" not in game_bench._output.toPlainText().lower()


def test_a_game_that_sent_junk_is_stopped(game_bench, stops) -> None:
    stopped = stops
    run = live_run()
    run.live.broken = "it sent something that was not a picture"
    game_bench._show_run(_Result(run))
    game_bench._game_ended()
    assert stopped == [run]
    assert "not a picture" in game_bench._output.toPlainText()


def test_a_game_left_playing_after_a_change_is_taken_away(game_bench, stops) -> None:
    """The game on screen would be the old version, and would look like the new one."""
    stopped = stops
    run = live_run()
    game_bench._show_run(_Result(run))
    (game_bench.project.directory / "src" / "game.py").write_text("PLAYER_SPEED = 9\n")
    game_bench._turn_finished(Turn(text="Done.", checkpoint="abc123"))
    assert stopped == [run]
    assert game_bench._game.isHidden()
    assert game_bench._game.stream is None


def test_a_turn_that_changed_nothing_leaves_the_game_playing(game_bench, stops) -> None:
    stopped = stops
    run = live_run()
    game_bench._show_run(_Result(run))
    game_bench._turn_finished(Turn(text="The player is the orange square."))
    assert not stopped
    assert game_bench._game.isVisibleTo(game_bench)


def test_a_game_gary_ran_and_then_changed_is_the_old_version(game_bench, stops) -> None:
    """Run in the turn is not enough: the code changed again after it started."""
    from opennest.agent.tools import ToolResult

    stopped = stops
    run = live_run()
    game_bench._progress(Step("playing", "running the project", live=run.live))
    (game_bench.project.directory / "src" / "game.py").write_text("PLAYER_SPEED = 2\n")
    turn = Turn(text="Done.", checkpoint="abc123",
                tool_results=[("run_project", ToolResult(True, "running", run=run))])
    game_bench._turn_finished(turn)
    assert stopped == [run]
    assert game_bench._game.isHidden()


def test_closing_the_project_stops_the_game_it_is_showing(game_bench, stops) -> None:
    stopped = stops
    run = live_run()
    game_bench._show_run(_Result(run))
    game_bench.toolbox.last_run = None
    game_bench.release()
    assert stopped == [run]
    assert game_bench._game.stream is None


@needs_sandbox
def test_run_game_plays_in_the_panel_through_the_real_thread(game_bench) -> None:
    """The one test here with a real game: the button, the worker, the sandbox, a key."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    started = time.monotonic()
    game_bench._run()
    assert pump(4, lambda: game_bench._game.current_frame() is not None), "no picture"
    assert time.monotonic() - started < 3.5, "the picture waited for the startup check"
    assert not game_bench._send_button.isEnabled(), "a message could race the run"
    assert pump(8, lambda: game_bench._thread is None)
    assert game_bench._game.hasFocus(), "the child pressed Run Game; the game has the keys"
    assert game_bench._send_button.isEnabled()

    def player_x():
        frame = game_bench._game.current_frame()
        for x in range(frame.width):
            for y in range(0, frame.height, 4):
                i = (y * frame.width + x) * 4
                if frame.data[i:i + 4] == bytes((62, 142, 214, 255)):
                    return x

    before = player_x()
    QTest.keyPress(game_bench._game, Qt.Key.Key_Left)
    assert pump(2, lambda: (player_x() or 999) < before - 40), "the key did not move it"
    QTest.keyRelease(game_bench._game, Qt.Key.Key_Left)

    process = game_bench._live_run.process
    game_bench._stop()
    assert pump(6, lambda: process.poll() is not None), "Stop left the game running"
    pump(0.3)
    assert game_bench._output.toPlainText() == "Stopped."
    assert not game_bench._stop_button.isEnabled()


# ----------------------------------------------------- Phase 13B: pop out, put back

def _playing(bench):
    run = live_run()
    bench._show_run(_Result(run))
    return run


def test_a_playing_game_can_be_popped_out_and_is_the_same_game(game_bench) -> None:
    from opennest.ui.workbench import POP_OUT, PUT_BACK

    run = _playing(game_bench)
    assert game_bench._pop_button.isVisibleTo(game_bench)
    assert game_bench._pop_button.text() == POP_OUT
    game = game_bench._game
    game_bench._pop_out()
    window = game_bench._game_window
    assert window is not None and not window.isHidden()
    assert game.window() is window, "the game moved into its own window"
    assert game.stream is run.live, "the same stream -- nothing restarted"
    assert game_bench._pop_button.text() == PUT_BACK
    assert game_bench._popped_note.isVisibleTo(game_bench)
    assert window.windowTitle().startswith("Eagle Patrol")
    assert game_bench._output.toPlainText().startswith("Your game is in its own window")


def test_put_back_brings_it_home_still_playing(game_bench) -> None:
    run = _playing(game_bench)
    game = game_bench._game
    game_bench._pop_out()
    game_bench._game_window.back.click()
    assert game.window() is game_bench.window(), "back in the Workbench"
    assert game_bench._game_window.isHidden()
    assert game.stream is run.live and game.running
    assert game.isVisibleTo(game_bench)
    assert not game_bench._popped_note.isVisibleTo(game_bench)


def test_closing_the_window_puts_it_back_and_does_not_stop_it(game_bench, stops) -> None:
    run = _playing(game_bench)
    game_bench._pop_out()
    game_bench._game_window.close()
    assert not game_bench._popped and game_bench._game.running
    assert stops == [], "closing the window is not Stop"
    assert run.output.stopped is False


def test_code_on_screen_leaves_a_popped_game_where_it_is(game_bench) -> None:
    _playing(game_bench)
    game_bench._pop_out()
    game_bench._progress(Step("changed", "changed src/game.py", path="src/game.py",
                              content="A = 1\n", changed_lines=(0,)))
    assert not game_bench._game.isHidden(), "the game in its own window is not hidden"
    assert game_bench._output.toPlainText() == "A = 1\n"


def test_a_stale_game_is_taken_home_and_away(game_bench, stops) -> None:
    run = _playing(game_bench)
    game_bench._pop_out()
    game = game_bench.project.entrypoint_path
    game.write_text(game.read_text() + "\n# changed\n")
    game_bench._retire_game_if_stale()
    assert not game_bench._popped and game_bench._game_window.isHidden()
    assert run in stops and game_bench._game.isHidden()


def test_closing_the_project_with_the_game_out_is_clean(qt_app, project, stops) -> None:
    from opennest.ui.workbench import Workbench

    bench = Workbench(project, AgentController(project, ScriptedProvider([]),
                                               Toolbox(project)))
    bench.show()
    run = live_run()
    bench._show_run(_Result(run))
    bench._pop_out()
    window = bench._game_window
    bench.release()
    bench.close()
    assert window.isHidden() and run in stops


def test_the_window_opens_at_the_games_own_size_and_never_bigger_than_the_screen() -> None:
    from PySide6.QtCore import QSize

    from opennest.ui.game_window import BAR_HEIGHT, window_size

    assert window_size(640, 480, QSize(2000, 1200)) == QSize(640, 480 + BAR_HEIGHT)
    assert window_size(320, 240, QSize(2000, 1200)).width() == 600   # room for the bar
    small = window_size(1280, 960, QSize(1000, 700))
    assert small.width() <= 900 and small.height() <= 630
    assert abs(small.width() / (small.height() - BAR_HEIGHT) - 1280 / 960) < 0.02


def test_tab_in_the_window_reaches_put_back(game_bench) -> None:
    _playing(game_bench)
    game_bench._pop_out()
    window = game_bench._game_window
    order = []
    widget = game_bench._game
    for _ in range(3):
        widget = widget.nextInFocusChain()
        order.append(widget)
    assert window.back in order, "Tab leaves the game for the Put back button"


@needs_sandbox
def test_a_real_game_keeps_drawing_through_pop_out_and_put_back(game_bench) -> None:
    """The real game, the real sandbox: pictures keep arriving in both places."""
    game_bench._run()
    assert pump(6, lambda: game_bench._game.current_frame() is not None), "no picture"
    assert pump(8, lambda: game_bench._thread is None)

    def sequence():
        frame = game_bench._game.current_frame()
        return frame.sequence if frame is not None else -1

    # A picture is sent only when it changes, and the Basic Game only moves on a key:
    # hold one down through the stream, in both places.
    stream = game_bench._game.stream
    game_bench._pop_out()
    popped_at = sequence()
    stream.send_key("K_RIGHT", True)
    assert pump(3, lambda: sequence() > popped_at + 5), "no new pictures once popped out"
    stream.send_key("K_RIGHT", False)
    game_bench._put_back()
    back_at = sequence()
    stream.send_key("K_LEFT", True)
    assert pump(3, lambda: sequence() > back_at + 5), "no new pictures once put back"
    stream.send_key("K_LEFT", False)
    assert game_bench._game.stream is stream, "one stream the whole time"
    process = game_bench._live_run.process
    game_bench._stop()
    assert pump(6, lambda: process.poll() is not None)
