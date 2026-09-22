"""Workbench -- the project workspace.

DESIGN_DOC.md section 11 and WORKORDER_01 section 14. Three panels: what is in the
project, what happened when it ran, and the Assistant. Deliberately simpler than an IDE;
technical detail stays visually secondary.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
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
from opennest.ai import images
from opennest.ai.router import models_for_project, models_that_can_read, why_unavailable
from opennest.assets import kinds
from opennest.assets import manager as assets
from opennest.execution import arduino, outputs
from opennest.execution.python_runner import stop_project
from opennest.projects.manager import Project
from opennest.security.sandbox import visible_files
from opennest.ui.common import horizontal_rule, section_label, status_row
from opennest.ui.worker import AgentWorker, ImageWorker, run_in_thread
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
    #: A model the child picked. MainWindow owns the provider, so it decides whether the
    #: switch may happen -- a cloud model needs the master switch and, usually, consent.
    model_change_requested = Signal(str)

    def __init__(
        self,
        project: Project,
        controller: AgentController,
        versions: VersionHistory | None = None,
        *,
        allow_cloud: bool = False,
        credentials=None,
        upload_policy=None,
        starter_idea: str | None = None,
        sync=None,
    ) -> None:
        super().__init__()
        self.project = project
        self.controller = controller
        self.toolbox: Toolbox = controller.toolbox
        self.versions = versions
        self.allow_cloud = allow_cloud
        #: GitHub backup, or None when there is none. Optional for the same reason
        #: ``versions`` is: the Workbench has to work without it, and every headless
        #: test that predates Phase 9 constructs one without it.
        self.sync = sync
        #: The review branch this turn is happening on, when the PR policy asked for
        #: one. Empty for the default policy, which is every ordinary session.
        self._review_branch = ""
        #: Whether sending a sketch to a board is allowed *now*. A callable for the same
        #: reason ``Toolbox.network_policy`` is one: the answer can be a parent dialog,
        #: so it cannot be known when the project opened. Default refuses -- an
        #: application that could not ask has not been told yes.
        self.upload_policy = upload_policy or (lambda: False)
        #: Only ever asked whether a key exists, never for its value. Injectable so the
        #: headless tests do not depend on what is in the developer's own Keychain.
        self.credentials = credentials
        self._thread = None
        #: Files dropped onto the chat, waiting to go with the next message.
        self._pending: list[assets.Asset] = []
        #: Pictures present before the current run, so its own output can be told apart
        #: from what the child imported earlier.
        self._images_before: outputs.Snapshot = {}
        self._build()
        # WORKORDER_01 section 12: a file can be dragged onto the chat, the file panel
        # or the asset panel. One handler covers all three; where it landed decides
        # whether it is also attached to the next message.
        self.setAcceptDrops(True)
        self.refresh_files()
        if starter_idea:
            self.suggest(starter_idea)

    def suggest(self, idea: str) -> None:
        """Put a starter idea in the message box, ready to send or edit.

        Filled in rather than sent: a child who picked "Maze" usually wants to say
        something more before anything is built, and sending on their behalf takes that
        away. WORKORDER_01 sections 5 and 27.
        """
        self._input.setText(self._starter_sentence(idea))
        self._input.setFocus()

    def _starter_sentence(self, idea: str) -> str:
        """Turn a card's two words into something worth sending."""
        if self.project.profile.generates:
            return f"Make a picture of {idea.lower()}"
        return f"Make a {idea.lower()}"

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

        self._models = QComboBox()
        self._models.setToolTip("Which AI is helping")
        self._models.currentIndexChanged.connect(self._model_picked)
        self.refresh_models()

        self._model_status = status_row(self._status_name(), "idle", "Loading")

        row.addWidget(back)
        row.addSpacing(8)
        row.addWidget(title)
        row.addWidget(kind)
        row.addStretch(1)
        row.addWidget(section_label("Model"))
        row.addWidget(self._models)
        row.addSpacing(12)
        row.addWidget(self._model_status)
        return row

    def refresh_models(self) -> None:
        """Rebuild the picker. Called at build time and after Settings changes.

        DESIGN_DOC section 13 wants the two kinds visually distinguished and forbids
        presenting cloud models as better -- so every row says where the model runs and
        nothing says which is preferable. A model that cannot be used yet is shown
        disabled with the reason, rather than hidden: a parent looking for "where is
        Claude" should find it, not wonder.
        """
        current = self.current_model_id()
        self._models.blockSignals(True)
        self._models.clear()
        for entry in models_for_project(self.project.profile, allow_cloud=True):
            where = "Internet" if entry.info.requires_internet else "On this Mac"
            self._models.addItem(f"{entry.info.name} — {where}", entry.info.id)
            index = self._models.count() - 1
            reason = why_unavailable(
                entry, allow_cloud=self.allow_cloud, credentials=self.credentials
            )
            if reason:
                self._models.setItemData(index, reason, Qt.ItemDataRole.ToolTipRole)
                item = self._models.model().item(index)
                if item is not None:
                    item.setEnabled(False)
        self.select_model(current or self._active_model_id())
        self._models.blockSignals(False)

    def current_model_id(self) -> str | None:
        return self._models.currentData() if self._models.count() else None

    def _active_model_id(self) -> str | None:
        info = getattr(self.controller.provider, "info", None)
        return getattr(info, "id", None)

    def select_model(self, model_id: str | None) -> None:
        """Move the picker without asking for a switch. Used to put it back."""
        if not model_id:
            return
        index = self._models.findData(model_id)
        if index < 0:
            return
        blocked = self._models.signalsBlocked()
        self._models.blockSignals(True)
        self._models.setCurrentIndex(index)
        self._models.blockSignals(blocked)

    def _model_picked(self) -> None:
        model_id = self._models.currentData()
        if model_id and model_id != self._active_model_id():
            self.model_change_requested.emit(model_id)

    def _status_name(self) -> str:
        """"LOCAL AI" or "CLOUD AI" -- section 34 wants the difference always visible."""
        info = getattr(self.controller.provider, "info", None)
        return "Cloud AI" if getattr(info, "requires_internet", False) else "Local AI"

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

        # DoD 34: a chart is only a result if somebody can see it. Hidden until a run
        # actually produces a picture, so a Games project never grows an empty frame.
        self._chart_caption = QLabel()
        self._chart_caption.setProperty("role", "mono")
        self._chart_caption.hide()
        self._chart = QLabel()
        self._chart.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart.hide()
        layout.addWidget(self._chart_caption)
        layout.addWidget(self._chart, 2)
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

        # WORKORDER_01 section 30 shows "✓ Compile" against "▶ Run Game": a tick for
        # checking the code, a play arrow for making something happen.
        profile = self.project.profile
        mark = "✓" if profile.can_compile else "▶"
        self._run_button = QPushButton(f"{mark}  {profile.run_label}")
        self._run_button.setProperty("role", "primary")
        self._run_button.clicked.connect(self._run)

        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self._stop)
        self._stop_button.setEnabled(False)
        # Nothing to stop in a project that compiles or generates: both finish on their
        # own, and neither leaves anything running.
        self._stop_button.setVisible(profile.can_run)

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
        if profile.can_compile:
            row.addSpacing(16)
            for widget in self._hardware_controls():
                row.addWidget(widget)
        row.addSpacing(16)
        row.addWidget(self._undo_button)
        row.addSpacing(16)
        row.addWidget(section_label("Build Style"))
        row.addWidget(self._style)
        row.addStretch(1)
        row.addWidget(self._saved)
        return row

    def _hardware_controls(self) -> list[QWidget]:
        """Board picker and Upload, for a project that compiles for a device.

        The board list comes from arduino-cli, never from a list written down here:
        WORKORDER_01 section 8 forbids inventing hardware details, and the name of a
        board a child does not own is a hardware detail. Nothing is preselected for the
        same reason -- choosing a board for them would choose every pin on it.
        """
        self._board = QComboBox()
        self._board.setToolTip("Which Arduino do you have?")
        self._board.currentIndexChanged.connect(self._board_picked)

        self._upload_button = QPushButton("Send to Board")
        self._upload_button.setToolTip("Put this sketch onto the Arduino")
        self._upload_button.clicked.connect(self._upload)

        self._refresh_boards()
        return [section_label("Board"), self._board, self._upload_button]

    def _refresh_boards(self) -> None:
        """Fill the board picker, or say plainly why it is empty."""
        self._board.blockSignals(True)
        self._board.clear()
        if not arduino.available():
            self._board.addItem("Arduino tools not installed", None)
            self._board.setEnabled(False)
            self._upload_button.setEnabled(False)
            self._board.setToolTip(arduino.missing_message())
            self._board.blockSignals(False)
            return

        self._board.addItem("Choose your board…", None)
        try:
            available = arduino.boards()
        except arduino.ArduinoUnavailable as exc:
            self._board.addItem("Could not read the board list", None)
            self._board.setToolTip(str(exc))
            self._board.blockSignals(False)
            return

        chosen = self.project.manifest.arduino_board
        for board in available:
            self._board.addItem(board.name, board.fqbn)
        if chosen:
            index = self._board.findData(chosen)
            if index >= 0:
                self._board.setCurrentIndex(index)
        self._board.blockSignals(False)
        self._upload_button.setEnabled(bool(chosen))

    def _board_picked(self) -> None:
        """Remember the board on the project, so it is chosen once and not every time."""
        fqbn = self._board.currentData()
        if not fqbn or fqbn == self.project.manifest.arduino_board:
            return
        self.project.manifest.arduino_board = fqbn
        try:
            self.project.save()
        except OSError as exc:
            self._output.setPlainText(f"Could not save which board you picked: {exc}")
            return
        self._upload_button.setEnabled(True)
        self._output.setPlainText(
            f"Set to {self._board.currentText()}. Press Compile to check your sketch."
        )

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

        With cloud off this is empty and the child is told the limitation rather than
        sent after a model they cannot reach. With cloud on *and a key saved* it fills
        in on its own -- no change was needed here in Phase 6, which is what the
        catalogue lookup was for.
        """
        return [
            entry.info
            for entry in models_that_can_read(
                asset.kind, allow_cloud=self.allow_cloud, credentials=self.credentials
            )
        ]

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
        replacement = status_row(self._status_name(), state, text)
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
        # The model may run the project during the turn, so the chart it draws has to be
        # measured against the project as it was before the turn started.
        self._note_images()

        # WORKORDER_01 section 29A's PR policy branches *before* the change, the way its
        # own diagram does. Off by default, so this is "" for a normal child session.
        self._review_branch = self._begin_review_branch()

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
        self._back_up(made_changes=turn.checkpoint is not None)

    # -- GitHub backup (WORKORDER_01 section 29A) ---------------------------

    def _begin_review_branch(self) -> str:
        """Start a review branch if the parent's PR policy asks for one."""
        if self.sync is None or self.versions is None:
            return ""
        from opennest.github import backup

        return backup.begin_change(self.project.directory, self.sync.controls)

    def _back_up(self, *, made_changes: bool) -> None:
        """Apply the PR policy and queue a push. Never interrupts the child.

        Section 29A is explicit that this "should not add visible complexity to the
        child's normal experience", so nothing here says anything to them -- a failure
        is recorded for a parent and the work is already saved locally either way.
        """
        if self.sync is None:
            return
        from opennest.github import backup
        from opennest.github.transport import GitHubError
        from opennest.versioning.git_manager import GitError

        branch = getattr(self, "_review_branch", "")
        self._review_branch = ""
        try:
            if branch and made_changes:
                backup.finish_change(
                    self.project,
                    branch,
                    self.sync.controls,
                    self.sync.credentials,
                    queue=self.sync.queue,
                )
            self.sync.queue_project(self.project)
            self.sync.sweep()
        except (GitError, GitHubError, OSError):
            # The checkpoint is saved. A backup that could not be arranged is not
            # something to stop a child over.
            return

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
            # Not "close its window": a Raspberry Pi test loop is a console program and
            # has no window to close. Stop is true for both, and it is right there.
            self._output.setPlainText("The project is running. Press Stop when you are done.")
            self._stop_button.setEnabled(True)
            return
        body = run.stdout if run.ok else run.failure_text
        self._output.setPlainText(body or "(no output)")
        self._show_any_chart()

    def _show_any_chart(self, relative: str | None = None) -> None:
        """Put a picture on screen (DoD 34).

        With no argument, works out what the run produced by comparing the project
        before and after, rather than trusting the model to report where it saved
        something. See :mod:`opennest.execution.outputs`.

        ``relative`` is for the case where the application already knows, because it
        put the file there itself -- a generated image.
        """
        if relative is None:
            produced = outputs.images_written(self.project.directory, self._images_before)
            if not produced:
                return
            newest, extra_count = produced[0], len(produced) - 1
        else:
            newest, extra_count = relative, 0

        pixmap = QPixmap(str(self.project.directory / newest))
        if pixmap.isNull():
            return
        self._chart.setPixmap(
            pixmap.scaled(
                self._chart.width() or 420,
                320,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        extra = f"  (+{extra_count} more)" if extra_count else ""
        self._chart_caption.setText(f"{newest}{extra}")
        self._chart_caption.show()
        self._chart.show()

    def _note_images(self) -> None:
        """Remember which pictures existed before something runs."""
        self._images_before = outputs.snapshot(self.project.directory)

    def _run(self) -> None:
        """The main button: run, compile, or generate, depending on the profile.

        This used to always dispatch ``run_project``. On an Arduino project, which has no
        run command and no such tool, that showed the child a message written for the
        model: "'run_project' is not available here. You can use: read_file, ...".
        """
        profile = self.project.profile
        if profile.generates:
            self._generate_image()
            return

        self._note_images()
        tool = "run_project" if profile.can_run else "compile_project"
        result = self.toolbox.dispatch(tool, {})
        if result.run is not None:
            self._show_run(result)
        elif not result.ok:
            self._output.setPlainText(result.content)

    def _stop(self) -> None:
        if self.toolbox.last_run is not None:
            stop_project(self.toolbox.last_run)
        self._stop_button.setEnabled(False)
        self._output.setPlainText("Stopped.")

    # -- hardware -----------------------------------------------------------

    def _upload(self) -> None:
        """Send the compiled sketch to a connected board.

        A privileged application action: it crosses the project boundary on purpose, so
        it needs the parent gate first and gets the narrowest access that can work --
        write access to one serial port, nothing else. The sandbox is not relaxed for
        anything else, and the gate is the one that already exists (``arduino_upload``)
        rather than a second mechanism.
        """
        board = self.project.manifest.arduino_board
        if not board:
            self._output.setPlainText("Choose which Arduino you have first.")
            return

        try:
            ports = arduino.connected_ports()
        except arduino.ArduinoUnavailable as exc:
            self._output.setPlainText(str(exc))
            return

        recognised = [port for port in ports if port.board is not None] or ports
        if not recognised:
            self._output.setPlainText(
                "I cannot see an Arduino plugged in. Connect it with the USB cable and "
                "try again."
            )
            return

        port = recognised[0]
        if len(recognised) > 1:
            choice, accepted = QInputDialog.getItem(
                self, "Which one?", "Send it to:",
                [candidate.label for candidate in recognised], 0, False,
            )
            if not accepted:
                return
            port = next(c for c in recognised if c.label == choice)

        # Asked at the moment it matters, not when the project opened -- the answer can
        # be a dialog. Unanswered means no.
        if not self.upload_policy():
            self._output.setPlainText("A parent has not allowed sending to a board.")
            return

        self._output.setPlainText(f"Sending to {port.label}…")
        try:
            result = arduino.upload(self.project, board, port.address)
        except arduino.ArduinoUnavailable as exc:
            self._output.setPlainText(str(exc))
            return
        if result.ok:
            self._output.setPlainText(f"Sent to {port.label}.\n\n{result.stdout.strip()}")
        else:
            self._output.setPlainText(result.failure_text or "Sending to the board failed.")

    # -- image generation ---------------------------------------------------

    def _generate_image(self) -> None:
        """Ask the image service for a picture (PLAN.md decision D6).

        Not a project run: the process sandbox denies network, so a child's own code
        could never reach an image service. This is the application making the request,
        which is why the profile declares ``run_mode: generate`` and has no run command.
        """
        unmet = images.unmet_requirements(
            self.project.profile, allow_cloud=self.allow_cloud, credentials=self.credentials
        )
        if unmet:
            self._output.setPlainText(unmet)
            return

        description = self._input.text().strip()
        if not description:
            description, accepted = QInputDialog.getText(
                self, "Make a Picture", "What should the picture be?"
            )
            if not accepted or not description.strip():
                return
            description = description.strip()
        self._input.clear()

        self._busy(True)
        self._output.setPlainText("Making your picture. This takes about fifteen seconds…")
        self._say("You", f"Make a picture: {description}")

        worker = ImageWorker(self.project, description, credentials=self.credentials)
        worker.finished.connect(self._image_ready)
        worker.failed.connect(self._image_failed)
        self._thread = run_in_thread(self, worker)
        self._thread.finished.connect(self._thread_done)

    def _image_ready(self, asset) -> None:
        self._busy(False)
        self._show_any_chart(asset.path)
        self.refresh_files()
        # Section 13's rule, kept at the point a picture appears: Open Nest asked for
        # this image and saved it, and still has not looked at it.
        self._say(
            "Open Nest",
            f"Saved as {asset.path}. {asset.summary}\n"
            f"  Nothing has looked at the picture itself -- open it to see how it came out.",
        )

    def _image_failed(self, message: str) -> None:
        self._busy(False)
        self._output.setPlainText(message)
