"""Background work, so the interface never freezes.

WORKORDER_01 section 1: the UI must stay responsive while models load and generate, code
runs, and projects build. MLX generation is synchronous and takes seconds, so it happens
on a worker thread and reports back through Qt signals.
"""

from __future__ import annotations

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
            self.failed.emit(f"Something went wrong: {exc}")
        else:
            self.finished.emit(turn)


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


def run_in_thread(parent: QObject, worker: QObject) -> QThread:
    """Move ``worker`` onto a new thread, start it, and clean up when it finishes.

    The thread is parented so Qt does not garbage-collect it mid-run -- a classic way to
    make PySide6 crash with no traceback.
    """
    thread = QThread(parent)
    worker.setParent(None)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    for signal_name in ("finished", "failed", "ready"):
        signal = getattr(worker, signal_name, None)
        if signal is not None:
            signal.connect(thread.quit)

    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
