"""Background work, so the interface never freezes.

WORKORDER_01 section 1: the UI must stay responsive while models load and generate, code
runs, and projects build. MLX generation is synchronous and takes seconds, so it happens
on a worker thread and reports back through Qt signals.
"""

from __future__ import annotations

import contextlib

from PySide6.QtCore import QObject, QThread, Signal

from opennest.agent.controller import AgentController, Turn
from opennest.ai.provider import ProviderError


class AgentWorker(QObject):
    """Runs one agent turn off the UI thread."""

    chunk = Signal(str)        # streamed text as it arrives
    finished = Signal(object)  # Turn
    failed = Signal(str)       # message fit for a person to read

    def __init__(self, controller: AgentController, text: str, attachments=()) -> None:
        super().__init__()
        self.controller = controller
        self.text = text
        self.attachments = tuple(attachments)

    def run(self) -> None:
        try:
            turn: Turn = self.controller.send(
                self.text, attachments=self.attachments, on_text=self.chunk.emit
            )
        except ProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - a crash here must not kill the app
            # brand_design_guide.md section 2: "That didn't work" rather than "Something
            # went terribly wrong". The exception still goes through verbatim -- the calm
            # register is in the framing, not in withholding what happened.
            self.failed.emit(f"That didn't work. {exc}")
        else:
            self.finished.emit(turn)


class ImageWorker(QObject):
    """Generates one picture off the UI thread.

    Measured at 10-15 seconds against the real service (SPIKES.md section 12), which is
    far too long to block on: a frozen window for a quarter of a minute reads as a
    crash. The Image Creation profile is the only caller.
    """

    finished = Signal(object)  # assets.Asset
    failed = Signal(str)

    def __init__(self, project, description: str, *, credentials, transport=None) -> None:
        super().__init__()
        self.project = project
        self.description = description
        self.credentials = credentials
        self.transport = transport

    def run(self) -> None:
        from opennest.ai import images

        try:
            asset = images.generate_into(
                self.project,
                self.description,
                credentials=self.credentials,
                transport=self.transport,
            )
        except ProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - a crash here must not kill the app
            self.failed.emit(f"The picture could not be made: {exc}")
        else:
            self.finished.emit(asset)


class ModelLoader(QObject):
    """Loads a model off the UI thread; first load is the slow one."""

    ready = Signal()
    failed = Signal(str)

    def __init__(self, provider) -> None:
        super().__init__()
        self.provider = provider

    def run(self) -> None:
        try:
            self.provider.load()
        except ProviderError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"The local AI could not start: {exc}")
        else:
            self.ready.emit()


#: How long to give a worker to stop before giving up on it. Generous, because the
#: alternative to waiting is the crash this exists to prevent.
SHUTDOWN_WAIT_MS = 5000


def stop_thread(thread: QThread | None, timeout_ms: int = SHUTDOWN_WAIT_MS) -> None:
    """Ask a worker thread to finish, and wait for it. Safe to call on None or a dead one.

    **Destroying a widget while one of its worker threads is still running aborts the
    interpreter**, with ``QThread: Destroyed while thread is still running`` and no
    traceback. The test fixtures have quit-and-waited by hand since Phase 5 for exactly
    this reason, which meant the hazard was understood and guarded everywhere except in
    the application itself.

    Phase 11B made that reachable rather than theoretical: the setup wizard now inspects
    the Mac the moment the Local AI step opens, so there is a live thread during a step
    a parent may well press Quit Setup on. Every window that starts a worker now waits
    for it on the way out.
    """
    if thread is None:
        return
    try:
        if not thread.isRunning():
            return
        thread.quit()
        if not thread.wait(timeout_ms):
            # Better a wedged worker than a hard abort: the thread is left alone and the
            # window closes. Terminating a thread mid-call is its own kind of crash.
            thread.requestInterruption()
            _park(thread)
    except RuntimeError:
        # The underlying QThread was already deleted by Qt. Nothing to wait for.
        return


#: Threads that would not stop in time. Parked here, detached from their widget, so Qt
#: cannot destroy one while it is still running -- which is the abort this module exists
#: to prevent, and which the "leave it alone and close the window" comment above did not
#: actually achieve while the thread was still a child of the closing widget.
_PARKED: list[QThread] = []


def _park(thread: QThread) -> None:
    """Detach a thread that would not stop, so its parent's destruction cannot kill it.

    A leaked thread is a bounded cost -- it finishes its call and then idles. A QThread
    destroyed mid-run is ``abort()``, which takes the whole application with it and
    leaves a macOS crash report in front of a parent.
    """
    with contextlib.suppress(RuntimeError):
        thread.setParent(None)
        _PARKED.append(thread)


class WorkerThread(QThread):
    """A thread that calls one worker's ``run`` and then ends.

    The shape this replaced was the documented Qt idiom -- ``moveToThread`` plus
    ``started.connect(worker.run)`` -- and under PySide6 6.11 it did not work. Phase 12
    measured three separate ways for it to fail silently, each producing a thread that
    ran forever with the work never done, no exception and nothing logged:

    1. ``moveToThread`` needs an object with no parent, so ``setParent(None)`` is
       forced; after it the caller's local was the only reference, and every call site
       in the application dropped that local immediately. The worker was collected
       before the thread could call it.
    2. Keeping the worker alive was not enough. ``started.connect(worker.run)`` builds a
       temporary bound-method object that PySide6 does not keep either, so the
       connection decayed with the worker plainly still there.
    3. With both held, the work ran on the **main thread** -- the point of the exercise
       lost while every symptom looked healthy.

    Overriding ``run`` removes all three questions. Qt calls it on the new thread with
    no signal, no connection and no reference semantics in between; ``self._worker`` is
    an ordinary Python attribute of a live QThread.

    The worker is deliberately **not** moved to this thread. Nothing here receives
    signals or owns a timer, so affinity buys nothing -- and what matters for the
    handlers is the *receiver's* affinity, which is the GUI thread either way, so
    ``finished``/``failed``/``ready`` still arrive queued on the GUI thread.
    """

    def __init__(self, parent: QObject, worker: QObject) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:  # noqa: D102 - Qt's name, called on the new thread
        self._worker.run()


def run_in_thread(parent: QObject, worker: QObject) -> QThread:
    """Run ``worker.run()`` on its own thread and return the thread.

    The thread is parented so Qt does not garbage-collect it mid-run -- a classic way to
    make PySide6 crash with no traceback. Whoever starts one is responsible for calling
    :func:`stop_thread` before their widget is destroyed.

    The 980 tests passing while none of this worked is the thing to take from it: every
    test reaches the behaviour through an inline seam, so the threading was the one part
    of the application nothing exercised. ``spikes/phase12/probe_run_in_thread.py`` is
    the check that would have caught it, and ``tests/test_worker.py`` now pins it.
    """
    thread = WorkerThread(parent, worker)
    # No ``worker.deleteLater``: Python owns the worker through the thread's attribute,
    # and asking Qt to delete an object Python owns frees it twice -- measured as a
    # SIGSEGV. Python releases it when the thread wrapper goes, which is the same moment
    # and the safe one.
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
