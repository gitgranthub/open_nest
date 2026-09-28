"""Closing a project -- or quitting -- while Gary is still writing.

It used to abort the process. ``Workbench.release`` gave the turn's thread five seconds,
parked it, and carried on; a parked thread still running when the program exits is
destroyed by Qt, which aborts (``QThread: Destroyed while thread is still running``,
SIGABRT, a macOS crash report -- SPIKES.md section 26I). Now the turn is told to stop at
its next safe point and the Workbench waits for its thread to end.

Three layers: the budget that carries the stop, the controller ending a turn through it,
and the Workbench / MainWindow waiting for a real worker thread.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.budget import BudgetExhausted, CallBudget, MeteredProvider  # noqa: E402
from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import (  # noqa: E402
    Chunk,
    Message,
    ModelInfo,
    ModelProvider,
    Reply,
    ToolCall,  # noqa: E402
)
from tests.conftest import ScriptedProvider  # noqa: E402

STOPPED = "I stopped there because the project was closed."


class Streaming(ModelProvider):
    """A reply delivered a piece at a time, slowly, the way a long local reply is.

    ``before_call`` runs at the start of each call, which is how a test closes the
    project while Gary is writing a particular reply.
    """

    def __init__(self, replies=(), *, pieces: int = 5, delay: float = 0.0,
                 before_call=None) -> None:
        self.info = ModelInfo(id="streaming", name="Streaming", provider="fake")
        self.replies = list(replies)
        self.pieces, self.delay, self.before_call = pieces, delay, before_call
        self.calls = 0
        self.sent = 0
        self.closed = False
        self._reply = Reply()

    @property
    def is_loaded(self) -> bool:
        return True

    def load(self) -> None:
        pass

    def unload(self) -> None:
        pass

    def chat(self, messages, *, tools=None, settings=None) -> Iterator[Chunk]:
        self.calls += 1
        if self.before_call is not None:
            self.before_call(self.calls)
        reply = self.replies.pop(0) if self.replies else Reply(text="word " * self.pieces)
        self._reply = reply
        try:
            if reply.tool_calls:
                yield Chunk(done=True)
                return
            for _ in range(self.pieces):
                if self.delay:
                    time.sleep(self.delay)
                self.sent += 1
                yield Chunk(text="word ")
            yield Chunk(done=True)
        finally:
            self.closed = True

    def finish(self) -> Reply:
        return self._reply


# ------------------------------------------------------------ the budget

def test_a_stopped_budget_refuses_the_next_call() -> None:
    budget = CallBudget()
    budget.stop()
    assert budget.exhausted and budget.remaining == 0
    with pytest.raises(BudgetExhausted, match="stopped"):
        budget.begin("primary")


def test_a_stop_cuts_a_long_reply_off_at_its_next_piece() -> None:
    provider = Streaming(pieces=100)
    budget = CallBudget()
    metered = MeteredProvider(provider, budget)
    got = []
    with pytest.raises(BudgetExhausted):
        for chunk in metered.chat([Message(role="user", content="go")]):
            got.append(chunk)
            if len(got) == 3:
                budget.stop()
    assert len(got) == 3, "it kept streaming after the stop"
    assert provider.closed, "the reply underneath was left open"


def test_the_last_call_the_budget_allows_is_not_cut_off() -> None:
    """Only the stop ends a reply early. After its twelfth call is dispatched a budget
    reads as used up, and checking *that* per piece would kill the last legitimate call
    on its first word -- nearly shipped, caught here."""
    budget = CallBudget(limit=1)
    metered = MeteredProvider(Streaming(pieces=20), budget)
    chunks = list(metered.chat([Message(role="user", content="go")]))
    assert budget.exhausted
    assert sum(1 for c in chunks if c.text) == 20


# ------------------------------------------------------------ the controller

def test_a_stopped_turn_keeps_and_checkpoints_what_it_already_changed(project) -> None:
    """Gary makes an edit, and the project is closed while he writes his next reply."""
    from opennest.versioning.checkpoint import VersionHistory

    versions = VersionHistory(project)
    versions.start()
    if not versions.enabled:
        pytest.skip("checkpoints need git")
    edit = ToolCall("edit_file", {"path": "src/game.py", "old_text": "PLAYER_SPEED = 5",
                                  "new_text": "PLAYER_SPEED = 9"})
    holder = {}

    def close_during_second_reply(call: int) -> None:
        if call == 2:
            holder["controller"].stop()

    provider = Streaming([Reply(tool_calls=(edit,))], pieces=50,
                         before_call=close_during_second_reply)
    controller = AgentController(project, provider, Toolbox(project), versions=versions)
    holder["controller"] = controller
    turn = controller.send("make the player faster")

    assert "PLAYER_SPEED = 9" in (project.directory / "src" / "game.py").read_text()
    assert turn.checkpoint is not None, "the change was made and not saved"
    assert turn.text == STOPPED
    assert provider.calls == 2, "it went on asking the model after the stop"
    # The stop landed after that call had begun: one piece was made underneath, and
    # the reply ended there instead of running to its fifty.
    assert provider.sent <= 1, "the stopped reply was streamed anyway"
    assert provider.closed


def test_a_stop_before_the_turn_began_still_stops_it(project) -> None:
    """The child can quit in the instant between Send and the turn's first call."""
    provider = Streaming()
    controller = AgentController(project, provider, Toolbox(project))
    controller.stop()
    turn = controller.send("make me a game")
    assert provider.calls == 0
    assert turn.text == STOPPED


def test_a_turn_that_ran_out_of_calls_still_says_so() -> None:
    """The stopped wording is only for a stop, never for the real ceiling."""
    from opennest.agent import controller as module

    assert STOPPED not in module.AgentController._out_of_calls.__doc__


# ------------------------------------------------------------ waiting for the thread

def _pump(seconds: float, until=None) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if until is not None and until():
            return True
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return bool(until()) if until is not None else True


def test_waiting_cannot_deadlock_with_a_question_the_worker_asks_the_window(qt_app) -> None:
    """A turn can be waiting on the GUI thread itself -- a parent permission prompt is
    asked there. A blocking ``wait()`` would deadlock with it; this keeps the loop
    running, so the question is answered and the worker ends."""
    from PySide6.QtCore import QObject

    from opennest.ui import consent
    from opennest.ui.worker import run_in_thread, wait_for_thread

    class Asker(QObject):
        answer = None

        def run(self):
            time.sleep(0.1)
            self.answer = consent._on_gui_thread(lambda: 42)

    owner, asker = QObject(), Asker()
    thread = run_in_thread(owner, asker)
    started = time.monotonic()
    wait_for_thread(thread)
    assert asker.answer == 42
    assert time.monotonic() - started < 5


def test_waiting_for_no_thread_is_harmless() -> None:
    from opennest.ui.worker import wait_for_thread

    wait_for_thread(None)


def test_closing_a_project_mid_turn_stops_the_turn_and_waits_for_it(qt_app, project) -> None:
    """Through a real worker thread, the way Send runs a turn."""
    from opennest.ui import worker as worker_module
    from opennest.ui.workbench import Workbench

    provider = Streaming(pieces=400, delay=0.02)          # eight seconds if left alone
    bench = Workbench(project, AgentController(project, provider, Toolbox(project)))
    bench.show()
    parked_before = len(worker_module._PARKED)
    try:
        bench._input.setText("write me a very long story")
        bench._send()
        thread = bench._thread
        assert _pump(5, lambda: provider.sent > 3), "the turn never started writing"

        started = time.monotonic()
        bench.release()
        took = time.monotonic() - started

        try:
            running = thread.isRunning()
        except RuntimeError:          # deleted by Qt once it finished
            running = False
        assert not running, "release() returned with the turn still running"
        assert len(worker_module._PARKED) == parked_before, "the turn was parked"
        assert took < 3, f"stopping took {took:.1f} s"
        assert provider.sent < 400, "the reply was written to the end"
        assert "word word" not in bench._transcript.toPlainText(), (
            "a closing project showed the stopped turn's reply"
        )
    finally:
        bench.close()


def test_a_second_close_while_the_first_waits_is_ignored(qt_app, project, monkeypatch,
                                                         configured_credentials) -> None:
    """Command-Q twice, or the close button again, while Gary winds down."""
    from PySide6.QtGui import QCloseEvent

    from opennest.ui import main_window as module

    monkeypatch.setattr(module, "run_in_thread", lambda *a, **k: None)
    monkeypatch.setattr(module, "build_provider",
                        lambda model_id, **kw: ScriptedProvider([Reply(text="ok")]))
    window = module.MainWindow(credentials=configured_credentials)
    closes = []
    real_close = window._close_project_now

    def close_now():
        closes.append(True)
        event = QCloseEvent()
        window.closeEvent(event)      # arrives while this close is still in progress
        assert not event.isAccepted(), "a second close was accepted mid-close"
        real_close()

    window._close_project_now = close_now
    window._close_project()
    assert closes == [True], "the project was closed twice"
    window._close_project()           # and once it is done, closing works again
    assert closes == [True, True]
    window.deleteLater()


def test_nothing_in_the_turn_path_blocks_on_a_thread_from_the_gui() -> None:
    """``release`` waits with the loop running; a plain ``QThread.wait()`` with a
    turn running is how a permission prompt would deadlock a quit."""
    import inspect

    from opennest.ui.workbench import Workbench

    source = inspect.getsource(Workbench.release)
    assert "wait_for_thread(self._thread)" in source
    assert ".wait(" not in source.replace("wait_for_thread(", "")
    _ = threading
