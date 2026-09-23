"""Background work actually happens — the one thing 980 tests never checked.

Phase 12 drove the real application for the first time and found that *no* worker in
it ran. ``run_in_thread`` used the documented Qt idiom, ``moveToThread`` plus
``started.connect(worker.run)``, and under PySide6 6.11 that combination loses the
worker: ``run()`` is never entered, nothing raises, nothing is logged, and the thread
sits there. The setup wizard stopped on "Checking this Mac..." with Continue and Back
disabled, the local model never finished loading, and a child's message to Gary went
nowhere.

The suite could not see it because every test reaches the behaviour through an inline
seam — ``LocalAIStep.inspect_now`` instead of ``enter``, a controller called directly
instead of an ``AgentWorker``. Those seams are right: they keep the suite hermetic and
let a recommendation be tested for a Mac nobody owns. But they meant the threading was
the one part of the application nothing exercised, so this file exercises it directly.

Runs under ``offscreen``, like the other Qt tests, and needs no display.
"""

from __future__ import annotations

import gc
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ``qt_app`` comes from tests/conftest.py.


def _spin(predicate, timeout_ms: int = 5000) -> bool:
    """Run the real event loop until ``predicate`` holds.

    A nested ``QEventLoop`` rather than ``QTest.qWait``: qWait spins
    ``processEvents`` on the GUI thread, which starves a Python worker of the GIL --
    measured at 140x slower in Phase 12, enough to turn a 0.02 s inspection into a
    minute and make a passing test look like a hang.
    """
    from PySide6.QtCore import QEventLoop, QTimer

    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        loop = QEventLoop()
        QTimer.singleShot(25, loop.quit)
        loop.exec()
        waited += 25
    return bool(predicate())


def _probe():
    """A worker that records the thread it ran on and emits a payload."""
    from PySide6.QtCore import QObject, Signal

    class Probe(QObject):
        finished = Signal(object)

        def __init__(self) -> None:
            super().__init__()
            self.ran_on: str | None = None

        def run(self) -> None:
            self.ran_on = threading.current_thread().name
            self.finished.emit(("payload", 1, 2))

    return Probe()


def test_a_worker_runs_even_though_the_caller_kept_no_reference(qt_app) -> None:
    """The defect exactly: every call site in the application drops its local.

    ``moveToThread`` needs an unparented object, so after ``setParent(None)`` the
    caller's local was the only thing holding the worker -- and PySide6 holds a
    receiver QObject weakly in a connection. This test starts a worker inside a
    function and forces a collection before the thread can get to it.
    """
    from PySide6.QtCore import QObject

    from opennest.ui.worker import run_in_thread, stop_thread

    owner = QObject()
    seen: list = []
    threads: list = []

    def start() -> None:
        worker = _probe()
        worker.finished.connect(seen.append)
        threads.append(run_in_thread(owner, worker))
        # `worker` goes out of scope here, exactly as it does in the wizard, the
        # workbench, the main window and the GitHub sweep.

    start()
    gc.collect()

    assert _spin(lambda: bool(seen)), (
        "the worker never ran: run_in_thread dropped it, which is silent -- no "
        "exception, no log, just a thread that does nothing forever"
    )
    assert seen[0] == ("payload", 1, 2)
    stop_thread(threads[0])


def test_the_work_happens_off_the_gui_thread(qt_app) -> None:
    """Otherwise the window freezes, which is the whole reason this module exists.

    Worth asserting rather than assuming: one intermediate fix during Phase 12 made
    the worker run again *on the main thread*, which fixes every visible symptom and
    none of the point.
    """
    from PySide6.QtCore import QObject

    from opennest.ui.worker import run_in_thread, stop_thread

    owner = QObject()
    worker = _probe()
    done: list = []
    worker.finished.connect(done.append)
    thread = run_in_thread(owner, worker)

    assert _spin(lambda: bool(done))
    assert worker.ran_on is not None
    assert worker.ran_on != threading.main_thread().name, (
        f"the worker ran on {worker.ran_on!r}, so a long turn would freeze the window"
    )
    stop_thread(thread)


def test_a_result_is_delivered_on_the_gui_thread(qt_app) -> None:
    """Qt widgets belong to the GUI thread, and a handler is what touches them.

    ``MainWindow`` connected ``loader.ready`` to a *lambda*, which has no receiver
    QObject for PySide6 to find a thread affinity on, so the handler ran on the worker
    thread -- swapping a Flight Deck status row and stopping the eagle's timer from
    there. Qt said so twice ("Cannot set parent, new parent is in a different thread",
    "Timers cannot be stopped from another thread") and nothing was listening.
    """
    from PySide6.QtCore import QObject

    from opennest.ui.worker import run_in_thread, stop_thread

    class Receiver(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.handled_on: str | None = None

        def handle(self, _payload) -> None:
            self.handled_on = threading.current_thread().name

    receiver = Receiver()
    worker = _probe()
    worker.finished.connect(receiver.handle)
    thread = run_in_thread(receiver, worker)

    assert _spin(lambda: receiver.handled_on is not None)
    assert receiver.handled_on == threading.main_thread().name, (
        f"the handler ran on {receiver.handled_on!r}; anything it does to a widget is "
        f"undefined behaviour"
    )
    stop_thread(thread)


def test_stopping_a_thread_that_will_not_stop_detaches_it_rather_than_letting_qt_kill_it(
    qt_app,
) -> None:
    """A QThread destroyed while running is ``abort()``, not an exception.

    ``stop_thread`` always claimed to leave a wedged worker alone and close the window.
    It did not: the thread stayed a child of the closing widget, so Qt destroyed it
    anyway. Phase 12 measured that as exit 134 with a macOS crash report.
    """
    from PySide6.QtCore import QObject, Signal

    from opennest.ui.worker import _PARKED, run_in_thread, stop_thread

    class Stubborn(QObject):
        finished = Signal(object)

        def __init__(self) -> None:
            super().__init__()
            self.release = threading.Event()

        def run(self) -> None:
            self.release.wait(30)
            self.finished.emit(None)

    owner = QObject()
    worker = Stubborn()
    thread = run_in_thread(owner, worker)
    _spin(lambda: thread.isRunning(), timeout_ms=2000)

    before = len(_PARKED)
    stop_thread(thread, timeout_ms=200)   # it will not stop in 200 ms
    assert len(_PARKED) == before + 1, "a thread that would not stop was not parked"
    assert thread.parent() is None, (
        "the thread is still a child of its owner, so destroying the owner destroys a "
        "running thread -- which aborts the interpreter"
    )

    # Let it go, and wait for it to actually end so the session does not carry a live
    # thread into the next test. A finished thread is deleteLater'd, so asking a
    # deleted wrapper anything raises rather than answering False.
    worker.release.set()

    def ended() -> bool:
        try:
            return thread.isFinished()
        except RuntimeError:
            return True

    _spin(ended, timeout_ms=5000)


def test_nothing_connects_a_lambda_to_a_worker_signal() -> None:
    """A lambda handler runs on the worker thread. Grepped, because it is invisible.

    PySide6 decides a connection's type from the receiver's thread affinity, and a
    plain lambda has no receiver to ask -- so a cross-thread signal is delivered
    directly, on the emitting thread. A bound method of a QObject gets a queued
    connection and arrives on the GUI thread. The difference is one character of
    syntax and produces widget access from the wrong thread, which Qt warns about and
    nobody reads.

    Tokenised rather than imported, in the same spirit as
    ``test_nothing_still_reads_the_schema_1_starter_field``.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parent.parent / "opennest"
    signals = {"finished", "failed", "ready", "progress", "chunk"}
    offenders: list[str] = []

    for path in sorted(package.rglob("*.py")):
        if "starters" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr in signals
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id in {"worker", "loader"}
            ):
                continue
            if node.args and isinstance(node.args[0], ast.Lambda):
                offenders.append(
                    f"{path.relative_to(package.parent)}:{node.lineno}: "
                    f"{node.func.value.value.id}.{node.func.value.attr}.connect(lambda ...)"
                )

    assert not offenders, (
        "a lambda connected to a worker signal runs on the worker thread:\n"
        + "\n".join(offenders)
    )
