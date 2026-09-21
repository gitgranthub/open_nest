"""Workbench -- the project workspace.

DESIGN_DOC.md section 11 and WORKORDER_01 section 14. Three panels: what is in the
project, what happened when it ran, and the Assistant. Deliberately simpler than an IDE;
technical detail stays visually secondary.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.router import models_that_can_read
from opennest.assets import kinds
from opennest.assets import manager as assets
from opennest.execution.python_runner import stop_project
from opennest.projects.manager import Project
from opennest.security.sandbox import visible_files
from opennest.ui.common import horizontal_rule, section_label, status_row
from opennest.ui.worker import AgentWorker, run_in_thread
from opennest.versioning.checkpoint import VersionHistory
from opennest.versioning.git_manager import GitError, SecretsFound


def _first_bytes(source: Path, count: int = 64) -> bytes:
    """Enough of a dropped file to tell what it actually is, before importing it."""
    try:
        with Path(source).open("rb") as stream:
            return stream.read(count)
    except OSError:
        return b""


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

    def __init__(
        self,
        project: Project,
        controller: AgentController,
        versions: VersionHistory | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.controller = controller
        self.toolbox: Toolbox = controller.toolbox
        self.versions = versions
        self._thread = None
        #: Files dropped onto the chat, waiting to go with the next message.
        self._pending: list[assets.Asset] = []
        self._build()
        # WORKORDER_01 section 12: a file can be dragged onto the chat, the file panel
        # or the asset panel. One handler covers all three; where it landed decides
        # whether it is also attached to the next message.
        self.setAcceptDrops(True)
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
        """Files and Assets, as WORKORDER_01 section 14 and DESIGN_DOC.md both show them."""
        frame, layout = panel("Project")
        self._files = QListWidget()
        self._files.itemActivated.connect(self._open_file)
        layout.addWidget(self._files, 2)

        layout.addWidget(section_label("Assets"))
        self._assets = QListWidget()
        self._assets.itemActivated.connect(self._describe_asset)
        layout.addWidget(self._assets, 1)

        add = QPushButton("+  Add to Project")
        add.setToolTip("Add a picture, a sound, a document or some data")
        add.clicked.connect(self._choose_files)
        layout.addWidget(add)
        self._assets_panel = frame
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

        # Shows what is going with the next message, so an attachment is never invisible.
        self._attached_label = QLabel()
        self._attached_label.setProperty("role", "mono")
        self._attached_label.hide()
        layout.addWidget(self._attached_label)

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
        self._chat_panel = frame
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

        # "Undo", not "revert commit". The child never learns that Git is involved.
        self._undo_button = QPushButton("Undo")
        self._undo_button.setToolTip("Go back to how the project was before the last change")
        self._undo_button.clicked.connect(self._undo)
        self._undo_button.setEnabled(bool(self.versions and self.versions.can_undo))

        self._style = QComboBox()
        self._style.addItem("Just build it", "build")
        self._style.addItem("Build it and teach me", "teach")
        self._style.setCurrentIndex(1 if self.controller.build_style == "teach" else 0)
        self._style.currentIndexChanged.connect(self._style_changed)

        self._saved = status_row("Project", "ready", "Saved")

        row.addWidget(self._run_button)
        row.addWidget(self._stop_button)
        row.addSpacing(16)
        row.addWidget(self._undo_button)
        row.addSpacing(16)
        row.addWidget(section_label("Build Style"))
        row.addWidget(self._style)
        row.addStretch(1)
        row.addWidget(self._saved)
        return row

    # -- behaviour ----------------------------------------------------------

    def refresh_files(self) -> None:
        """Files the child works on, and separately the things they have added."""
        imported = assets.list_assets(self.project)
        added = {asset.path for asset in imported}

        self._files.clear()
        for name in visible_files(self.project.directory):
            if name not in added:
                self._files.addItem(QListWidgetItem(name))

        self._assets.clear()
        for asset in imported:
            item = QListWidgetItem(asset.name)
            item.setData(Qt.ItemDataRole.UserRole, asset)
            item.setToolTip(asset.summary)
            self._assets.addItem(item)

    # -- adding files (WORKORDER_01 sections 10-13) --------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not paths:
            return
        event.acceptProposedAction()
        # Dropping onto the conversation means "and here is what I am talking about".
        # Dropping onto the file or asset panel just adds it to the project.
        self._add(paths, attach=self.is_chat_position(event.position().toPoint()))

    def is_chat_position(self, point) -> bool:
        """Whether a drop at this point landed on the conversation.

        Takes a point rather than an event so the rule that decides "attach to the next
        message" can be tested without synthesising a drag.
        """
        widget = self.childAt(point)
        while widget is not None:
            if widget is self._chat_panel:
                return True
            widget = widget.parentWidget()
        return False

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Add to Project")
        if names:
            self._add([Path(name) for name in names], attach=False)

    def _add(self, paths: list[Path], *, attach: bool) -> None:
        """Import each file, asking what it is, and say plainly what the AI can do with it."""
        for source in paths:
            role = self._ask_what_it_is(source)
            if role is None:
                continue
            try:
                asset = assets.import_file(self.project, source, role=role)
            except assets.AssetError as exc:
                QMessageBox.warning(self, "Open Nest", str(exc))
                continue

            self._say("Open Nest", assets.import_message(
                asset, self._model_info(), self._models_that_could_read(asset)
            ))
            if attach:
                self._pending.append(asset)

        self.refresh_files()
        self.controller.refresh_state()
        self._show_pending()

    def _ask_what_it_is(self, source: Path) -> str | None:
        """Section 12: the application classifies, and the child can change the answer."""
        guess = kinds.default_role(kinds.classify(source.name, _first_bytes(source)))
        labels = [kinds.ROLE_LABELS[role] for role in kinds.ROLES]
        chosen, accepted = QInputDialog.getItem(
            self, "Add to Project", f"What is {source.name}?",
            labels, kinds.ROLES.index(guess), False,
        )
        if not accepted:
            return None
        return kinds.ROLES[labels.index(chosen)]

    def _model_info(self):
        return getattr(self.controller.provider, "info", None)

    def _models_that_could_read(self, asset: assets.Asset):
        """Section 13's "offer a compatible model", only when one is actually usable.

        Cloud stays off until a parent turns it on (section 21), so today this is empty
        and the child is told the limitation rather than sent after a model they cannot
        reach. It fills in on its own when the catalogue gains one.
        """
        return [entry.info for entry in models_that_can_read(asset.kind)]

    def _show_pending(self) -> None:
        if not self._pending:
            self._attached_label.hide()
            return
        self._attached_label.setText(
            "Going with your next message: "
            + ", ".join(asset.name for asset in self._pending)
        )
        self._attached_label.show()

    def _describe_asset(self, item: QListWidgetItem) -> None:
        asset: assets.Asset = item.data(Qt.ItemDataRole.UserRole)
        self._output.setPlainText(f"{asset.path}\n\n{asset.summary}")

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
        attachments = tuple(self._pending)
        self._pending.clear()
        self._show_pending()
        self._say("You", text + "".join(f"\n  [ {a.name} ]" for a in attachments))
        self._busy(True)
        self.set_model_status("working", "Thinking")

        worker = AgentWorker(self.controller, text, attachments)
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
        self._refresh_undo()

    def _refresh_undo(self) -> None:
        self._undo_button.setEnabled(bool(self.versions and self.versions.can_undo))

    def _undo(self) -> None:
        if self.versions is None:
            return
        try:
            restored = self.versions.undo()
        except SecretsFound as exc:
            QMessageBox.warning(self, "Open Nest", str(exc))
            return
        except GitError as exc:
            QMessageBox.warning(self, "Open Nest", str(exc))
            return
        if restored is None:
            self._say("Open Nest", "There is no earlier version to go back to.")
            return
        self.refresh_files()
        self._refresh_undo()
        self.controller.refresh_state()
        self._output.clear()
        self._say("Open Nest", f"Went back to: {restored.label}")

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
