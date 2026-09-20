"""Workbench -- the project workspace.

DESIGN_DOC.md section 11 and WORKORDER_01 section 14. Three panels: what is in the
project, what happened when it ran, and the Assistant. Deliberately simpler than an IDE;
technical detail stays visually secondary.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.execution.python_runner import stop_project
from opennest.projects.manager import Project
from opennest.security.sandbox import visible_files
from opennest.ui.common import horizontal_rule, section_label, status_row
from opennest.ui.worker import AgentWorker, run_in_thread


def panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("role", "panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)
    layout.addWidget(section_label(title))
    return frame, layout


class Workbench(QWidget):
    """One project, one model, one conversation."""

    back_requested = Signal()

    def __init__(self, project: Project, controller: AgentController) -> None:
        super().__init__()
        self.project = project
        self.controller = controller
        self.toolbox: Toolbox = controller.toolbox
        self._thread = None
        self._build()
        self.refresh_files()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        outer.addLayout(self._header())
        outer.addWidget(horizontal_rule())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._files_panel())
        splitter.addWidget(self._output_panel())
        splitter.addWidget(self._assistant_panel())
        splitter.setSizes([200, 420, 380])
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, 1)

        outer.addWidget(horizontal_rule())
        outer.addLayout(self._footer())

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        back = QPushButton("←  Flight Deck")
        back.clicked.connect(self.back_requested.emit)

        title = QLabel(self.project.name)
        title.setProperty("role", "projectTitle")

        kind = QLabel(f"{self.project.profile.name} — Workbench")
        kind.setProperty("role", "mono")

        self._model_status = status_row("Local AI", "idle", "Loading")

        row.addWidget(back)
        row.addSpacing(8)
        row.addWidget(title)
        row.addWidget(kind)
        row.addStretch(1)
        row.addWidget(self._model_status)
        return row

    def _files_panel(self) -> QFrame:
        frame, layout = panel("Project")
        self._files = QListWidget()
        self._files.itemActivated.connect(self._open_file)
        layout.addWidget(self._files, 1)
        return frame

    def _output_panel(self) -> QFrame:
        frame, layout = panel("Build / Preview")
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setProperty("role", "mono")
        self._output.setPlaceholderText("Nothing has run yet.")
        layout.addWidget(self._output, 1)
        return frame

    def _assistant_panel(self) -> QFrame:
        frame, layout = panel("Assistant")
        self._transcript = QPlainTextEdit()
        self._transcript.setReadOnly(True)
        layout.addWidget(self._transcript, 1)

        entry = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Tell me your idea, or what to change.")
        self._input.returnPressed.connect(self._send)
        self._send_button = QPushButton("Send")
        self._send_button.setProperty("role", "primary")
        self._send_button.clicked.connect(self._send)
        entry.addWidget(self._input, 1)
        entry.addWidget(self._send_button)
        layout.addLayout(entry)
        return frame

    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self._run_button = QPushButton(f"▶  {self.project.profile.run_label}")
        self._run_button.setProperty("role", "primary")
        self._run_button.clicked.connect(self._run)

        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self._stop)
        self._stop_button.setEnabled(False)

        self._style = QComboBox()
        self._style.addItem("Just build it", "build")
        self._style.addItem("Build it and teach me", "teach")
        self._style.setCurrentIndex(1 if self.controller.build_style == "teach" else 0)
        self._style.currentIndexChanged.connect(self._style_changed)

        self._saved = status_row("Project", "ready", "Saved")

        row.addWidget(self._run_button)
        row.addWidget(self._stop_button)
        row.addSpacing(16)
        row.addWidget(section_label("Build Style"))
        row.addWidget(self._style)
        row.addStretch(1)
        row.addWidget(self._saved)
        return row

    # -- behaviour ----------------------------------------------------------

    def refresh_files(self) -> None:
        self._files.clear()
        for name in visible_files(self.project.directory):
            self._files.addItem(QListWidgetItem(name))

    def set_model_status(self, state: str, text: str) -> None:
        layout = self.layout().itemAt(0).layout()
        replacement = status_row("Local AI", state, text)
        layout.replaceWidget(self._model_status, replacement)
        self._model_status.deleteLater()
        self._model_status = replacement

    def _style_changed(self) -> None:
        self.controller.build_style = self._style.currentData()
        self.controller.refresh_state()

    def _open_file(self, item: QListWidgetItem) -> None:
        path = self.project.directory / item.text()
        try:
            self._output.setPlainText(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            self._output.setPlainText(f"{item.text()} is not a text file.")

    def _say(self, who: str, text: str) -> None:
        self._transcript.appendPlainText(f"{who}: {text}\n")

    def _busy(self, busy: bool) -> None:
        self._send_button.setEnabled(not busy)
        self._input.setEnabled(not busy)
        self._run_button.setEnabled(not busy)

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text or self._thread is not None:
            return
        self._input.clear()
        self._say("You", text)
        self._busy(True)
        self.set_model_status("working", "Thinking")

        worker = AgentWorker(self.controller, text)
        worker.finished.connect(self._turn_finished)
        worker.failed.connect(self._turn_failed)
        self._thread = run_in_thread(self, worker)
        self._thread.finished.connect(self._thread_done)

    def _thread_done(self) -> None:
        self._thread = None

    def _turn_finished(self, turn) -> None:
        self._busy(False)
        self.set_model_status("ready", "Ready")
        for _name, result in turn.tool_results:
            if result.run is not None:
                self._show_run(result)
        if turn.text:
            self._say("Assistant", turn.text)
        self.refresh_files()

    def _turn_failed(self, message: str) -> None:
        self._busy(False)
        self.set_model_status("attention", "Problem")
        self._say("Assistant", message)

    def _show_run(self, result) -> None:
        run = result.run
        if run.still_running:
            self._output.setPlainText("The project is running. Close its window to stop.")
            self._stop_button.setEnabled(True)
            return
        body = run.stdout if run.ok else run.failure_text
        self._output.setPlainText(body or "(no output)")

    def _run(self) -> None:
        result = self.toolbox.dispatch("run_project", {})
        if result.run is not None:
            self._show_run(result)
        elif not result.ok:
            self._output.setPlainText(result.content)

    def _stop(self) -> None:
        if self.toolbox.last_run is not None:
            stop_project(self.toolbox.last_run)
        self._stop_button.setEnabled(False)
        self._output.setPlainText("Stopped.")
