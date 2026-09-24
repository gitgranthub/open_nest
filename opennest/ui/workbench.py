"""Workbench -- the project workspace.

DESIGN_DOC.md section 11 and WORKORDER_01 section 14. Three panels: what is in the
project, what happened when it ran, and Gary. Deliberately simpler than an IDE;
technical detail stays visually secondary.

Who a message is attributed to is decided per message, not per call site. Gary speaks
about the project -- a turn's reply, an import, an undo, a picture. Open Nest speaks when
the machinery itself has something to report. ``_turn_failed`` is the case that shows the
difference.
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

from opennest import ASSISTANT_NAME, SYSTEM_NAME
from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai import images
from opennest.ai.router import models_for_project, models_that_can_read, why_unavailable
from opennest.assets import kinds
from opennest.assets import manager as assets
from opennest.execution import arduino, outputs, web_preview
from opennest.execution.python_runner import stop_project
from opennest.projects import starters
from opennest.projects.manager import (
    MANIFEST_NAME,
    Project,
    ProjectError,
    add_starter,
)
from opennest.security.sandbox import visible_files
from opennest.ui import about_gary, brand, theme
from opennest.ui import web_preview as web_preview_ui
from opennest.ui.common import horizontal_rule, section_label, status_row
from opennest.ui.worker import AgentWorker, ImageWorker, run_in_thread, stop_thread
from opennest.versioning.checkpoint import LABEL_SAVED_BY_HAND, VersionHistory
from opennest.versioning.git_manager import GitError, SecretsFound

#: WORKORDER_01 section 30's control, in the words it uses. DESIGN_DOC section 12's
#: button language asks for the verb the child believes in, and "Show Details" is on its
#: own list of good labels.
SHOW_DETAILS = "Show technical details"
HIDE_DETAILS = "Hide technical details"


def _first_bytes(source: Path, count: int = 64) -> bytes:
    """Enough of a dropped file to tell what it actually is, before importing it."""
    try:
        with Path(source).open("rb") as stream:
            return stream.read(count)
    except OSError:
        return b""


def headline_failure(run) -> str:
    """The one line worth leading with when a run fails.

    Deliberately **not** an explanation. Explaining the error is Gary's job and
    it happens in the conversation; inventing a friendly paraphrase here would be a
    second, dumber account of the same failure, and one that could be wrong. This picks
    the most informative line that is already there.

    For a Python traceback that is the last line -- ``NameError: name 'player_x' is not
    defined`` rather than eight frames of call stack above it. For ``arduino-cli`` it is
    the error summary. Choosing the last non-empty line is what makes it work for both
    without knowing which produced it, which matters because the compiler case is the one
    section 30 most needs (HANDOFF section 6C).

    A timeout is reported as a timeout, because for that case there is no error line at
    all and the raw text would say nothing a child could act on.
    """
    if getattr(run, "timed_out", False):
        return (
            f"The project was still running after {run.seconds:.0f} seconds, "
            "so it was stopped."
        )
    detail = (run.failure_text or "").strip()
    if not detail:
        return "It stopped, and said nothing about why."
    last = detail.splitlines()[-1].strip()
    if not last:
        return "It stopped early."
    hidden = len(detail.splitlines()) - 1
    if hidden > 0:
        return f"{last}\n\n({hidden} more lines of technical detail.)"
    return last


def panel(title: str, *, trailing: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """A titled panel. ``trailing`` sits beside the title, for a small affordance.

    Left-aligned next to the label rather than pushed to the right-hand edge, so it
    reads as belonging to the heading instead of as a second control.
    """
    frame = QFrame()
    frame.setProperty("role", "panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.setSpacing(8)
    if trailing is None:
        layout.addWidget(section_label(title))
    else:
        heading = QHBoxLayout()
        heading.setSpacing(4)
        heading.addWidget(section_label(title))
        heading.addWidget(trailing)
        heading.addStretch(1)
        layout.addLayout(heading)
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
        #: Whether this project had ever run successfully before the current attempt.
        #: Seeded from the manifest so reopening a working project does not re-award the
        #: milestone -- it is once per project, not once per session.
        self._worked_before = bool(project.manifest.last_successful_run)
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
        """``[ON/NEST]  ASTEROID GAME`` -- guide section 57's own example.

        The mark is the compact lockup in light mode and the nest alone in dark, because
        the delivery has no dark compact variant and one cannot be built here: it is a
        pre-composited black ON over a white-ish nest, so inverting it would blacken the
        nest, and rebuilding the lockup would mean guessing at the approved ON-to-nest
        proportions. Section 48 sanctions the nest-only mark "where the product identity
        is already clear from surrounding text", and a header carrying the project name
        and "Workbench" qualifies. The two are within a pixel of the same height, so the
        header does not change shape between schemes.

        The title and kind stack beside the mark rather than sitting next to it, so the
        height the mark needs is spent on content instead of whitespace -- section 57 is
        explicit that the Workbench must not give large areas to branding.
        """
        row = QHBoxLayout()
        row.setSpacing(12)

        back = QPushButton("←  Flight Deck")
        back.clicked.connect(self.back_requested.emit)

        dark = theme.is_dark()
        mark = brand.placed("workbench_nest" if dark else "workbench_compact", dark=dark)

        title = QLabel(self.project.name)
        title.setProperty("role", "projectTitle")

        kind = QLabel(f"{self.project.profile.name} — Workbench")
        kind.setProperty("role", "mono")

        names = QVBoxLayout()
        names.setSpacing(0)
        names.addStretch(1)
        names.addWidget(title)
        names.addWidget(kind)
        names.addStretch(1)

        self._models = QComboBox()
        self._models.setToolTip("Which AI is helping")
        self._models.currentIndexChanged.connect(self._model_picked)
        self.refresh_models()

        self._model_status = status_row(self._status_name(), "idle", "Loading")

        row.addWidget(back, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addLayout(names)
        row.addStretch(1)
        row.addWidget(section_label("Model"))
        row.addWidget(self._models, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(12)
        row.addWidget(self._model_status, 0, Qt.AlignmentFlag.AlignVCenter)
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

        # The empty state, and the one-click offer behind it. Shown only while there is
        # genuinely nothing in src/, so a starter can never appear over a child's work
        # -- and ``starters.apply`` refuses anyway, because a rule enforced only by
        # whichever button happens to call it is not a rule.
        self._empty_note = QLabel()
        self._empty_note.setProperty("role", "cardBody")
        self._empty_note.setWordWrap(True)
        self._empty_note.hide()
        layout.addWidget(self._empty_note)

        self._starter_buttons: list[QPushButton] = []
        for starter in starters.starters_for(self.project.profile):
            button = QPushButton(f"Add {starter.name}")
            button.setToolTip(starter.description)
            button.clicked.connect(lambda _=False, s=starter.id: self._add_starter(s))
            button.hide()
            layout.addWidget(button)
            self._starter_buttons.append(button)

        add = QPushButton("+  Add to Project")
        add.setToolTip("Add a picture, a sound, a document or some data")
        add.clicked.connect(self._choose_files)
        layout.addWidget(add)
        self._assets_panel = frame
        return frame

    def _output_panel(self) -> QFrame:
        frame, layout = panel("Build / Preview")

        # A website has no build output to read -- no process, no exit code, no stderr
        # -- so the panel holds the page itself instead of a transcript of a run that
        # never happens. Everything below still exists for the profiles that do run.
        self._web = None
        if self.project.profile.previews:
            self._web = web_preview_ui.WebPreview(self.project, self)
            layout.addWidget(self._web, 3)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setProperty("role", "mono")
        self._output.setPlaceholderText("Nothing has run yet.")
        # Small beside a rendered page, and the whole panel where there is no page.
        layout.addWidget(self._output, 0 if self._web is not None else 1)
        if self._web is not None:
            self._output.setMaximumHeight(110)
            self._web.blocked.connect(self._panel_text)

        # WORKORDER_01 section 30: "Errors should appear in child-friendly language
        # rather than raw tracebacks by default", with a Show technical details control
        # for troubleshooting. Until now the whole of ``RunResult.failure_text`` went
        # straight here -- and that property is documented as "what the repair loop needs
        # to see", so it is written for the model, not for a child. It is left exactly as
        # it is; what changes is that the panel no longer opens with it.
        self._details_button = QPushButton(SHOW_DETAILS)
        self._details_button.setToolTip("See the exact error the project produced")
        self._details_button.clicked.connect(self._toggle_details)
        self._details_button.hide()
        details_row = QHBoxLayout()
        details_row.addWidget(self._details_button)
        details_row.addStretch(1)
        layout.addLayout(details_row)
        #: Raw text for the run on screen, revealed only if asked for.
        self._technical_detail = ""
        #: The short version the panel opens with, kept so the toggle can come back.
        self._headline = ""
        self._details_shown = False

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
        # The panel is titled with his name, so this is where someone wonders who he is.
        # Nothing opens it: it is a glyph beside the heading and it waits to be clicked.
        self._about_gary = about_gary.info_button()
        frame, layout = panel(ASSISTANT_NAME, trailing=self._about_gary)
        self._transcript = QPlainTextEdit()
        self._transcript.setReadOnly(True)
        layout.addWidget(self._transcript, 1)

        # Guide sections 36, 37 and 53: a turn is a meaningful wait on a 4B local model,
        # it already runs off the GUI thread so the wings can actually keep moving
        # (section 52), and the bird sits inline beside real status text rather than
        # replacing it. Hidden whenever nothing is happening.
        self._activity = QWidget()
        # Transparent, or the container paints the window colour over the panel.
        self._activity.setProperty("role", "bare")
        activity = QHBoxLayout(self._activity)
        activity.setContentsMargins(0, 0, 0, 0)
        activity.setSpacing(10)
        self._eagle = brand.EagleActivityIndicator(
            self._activity, size=brand.EAGLE_INLINE, dark=theme.is_dark()
        )
        self._activity_text = QLabel()
        self._activity_text.setProperty("role", "cardBody")
        activity.addWidget(self._eagle, 0, Qt.AlignmentFlag.AlignVCenter)
        activity.addWidget(self._activity_text, 1, Qt.AlignmentFlag.AlignVCenter)
        self._activity.hide()
        layout.addWidget(self._activity)

        # Sections 38, 39 and 54: reserved for a milestone that has actually been
        # observed, so it stays rare enough to mean something. Never on a save.
        self._completion = QWidget()
        self._completion.setProperty("role", "bare")
        completion = QHBoxLayout(self._completion)
        completion.setContentsMargins(0, 0, 0, 0)
        completion.setSpacing(10)
        self._glasses = brand.placed("completion_glasses", dark=theme.is_dark())
        self._completion_text = QLabel()
        self._completion_text.setProperty("role", "cardTitle")
        completion.addWidget(self._glasses, 0, Qt.AlignmentFlag.AlignVCenter)
        completion.addWidget(self._completion_text, 1, Qt.AlignmentFlag.AlignVCenter)
        self._completion.hide()
        layout.addWidget(self._completion)

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

        # Section 29A saves automatically and the child is never asked to. That is the
        # right default and it is not the whole story: somebody who has just got a
        # chart looking right wants to *mark* that, not trust that something did. Undo
        # has always been the visible half of version history; this is the other half,
        # and it uses the same machinery rather than a second idea of saving.
        self._save_button = QPushButton("Save a Version")
        self._save_button.setToolTip(
            "Mark how the project is right now, so you can come back to it"
        )
        self._save_button.clicked.connect(self._save_version)
        self._save_button.setEnabled(self.versions is not None)

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
        row.addWidget(self._save_button)
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
            self._panel_text(f"Could not save which board you picked: {exc}")
            return
        self._upload_button.setEnabled(True)
        self._panel_text(
            f"Set to {self._board.currentText()}. Press Compile to check your sketch."
        )

    # -- behaviour ----------------------------------------------------------

    def refresh_files(self) -> None:
        """Files the child works on, and separately the things they have added."""
        imported = assets.list_assets(self.project)
        added = {asset.path for asset in imported}

        self._files.clear()
        for name in visible_files(self.project.directory):
            # ``project.json`` is Open Nest's own bookkeeping, not the child's work. It
            # was always in this list and always looked like a file they had made; Phase
            # 11 turned that into a visible contradiction, because a project started
            # empty showed "project.json" directly above the words "Nothing here yet."
            # It stays in ``visible_files`` -- the model is told what is really there --
            # and comes out of the panel a child reads.
            if name == MANIFEST_NAME or name in added:
                continue
            self._files.addItem(QListWidgetItem(name))

        self._assets.clear()
        for asset in imported:
            item = QListWidgetItem(asset.name)
            item.setData(Qt.ItemDataRole.UserRole, asset)
            item.setToolTip(asset.summary)
            self._assets.addItem(item)

        self._refresh_starter_offer()

    def _refresh_starter_offer(self) -> None:
        """Show "nothing here yet" and the starter buttons, or neither.

        The offer disappears the moment there is a file, which is the whole safety
        argument for it being one click: it is only ever offered into an empty project.
        """
        empty = not starters.has_own_files(self.project.directory / "src")
        offered = bool(self._starter_buttons) and empty
        if empty:
            self._empty_note.setText(
                "Nothing here yet.\nStart empty, or add a starter."
                if offered else
                f"Nothing here yet.\nTell {ASSISTANT_NAME} what you want to make."
            )
        self._empty_note.setVisible(empty)
        for button in self._starter_buttons:
            button.setVisible(offered)

    def _add_starter(self, starter_id: str) -> None:
        """Put a starter kit into a project that was started empty."""
        try:
            written = add_starter(self.project, starter_id)
        except ProjectError as exc:
            self._panel_text(str(exc))
            return
        self.refresh_files()
        # The model is told what it now has, the same way it is told after any other
        # change to the project. Gary knowing which foundation exists is the point of
        # recording the starter at all.
        self.controller.refresh_state()
        # Open Nest, not Gary: copying shipped files in is the application acting, and
        # PHASE_10_HANDOFF section 1 keeps that split.
        self._say(SYSTEM_NAME, f"Added {len(written)} files to the project.")
        if self.project.profile.previews:
            self._preview()

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

            # Gary, not Open Nest: brand guide section 22's "Asset Import" is one of its
            # worked Gary examples ("Got it. spaceship.png is now part of the project.").
            # What he says is unchanged -- import_message still states only what is
            # actually known about the file (HANDOFF section 6A).
            self._say(ASSISTANT_NAME, assets.import_message(
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
        self._panel_text(f"{asset.path}\n\n{asset.summary}")

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
            self._panel_text(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            self._panel_text(f"{item.text()} is not a text file.")

    def _say(self, who: str, text: str) -> None:
        self._transcript.appendPlainText(f"{who}: {text}\n")

    def _busy(self, busy: bool) -> None:
        self._send_button.setEnabled(not busy)
        self._input.setEnabled(not busy)
        self._run_button.setEnabled(not busy)

    # -- the waiting and completion hierarchies (guide sections 53, 54) -----

    def working(self, text: str = "") -> None:
        """Show the activity indicator, or hide it when ``text`` is empty.

        Guide section 46 is the reason this takes the status line rather than offering
        a way to start the eagle on its own: the graphic is never the only signal, so
        there is no call that produces a bird with nothing beside it.
        """
        self._activity_text.setText(text)
        self._activity.setVisible(bool(text))
        if text:
            self._eagle.start()
        else:
            self._eagle.stop()

    def completed(self, text: str = "") -> None:
        """Mark a real milestone, or clear the last one.

        Section 39 lists what this is *not* for -- every save, every model reply, every
        successful button press, every checkpoint. The single caller is a project's
        first working run, which happens once in a project's life.
        """
        self._completion_text.setText(text)
        self._completion.setVisible(bool(text))

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
        self.working(f"{ASSISTANT_NAME} is working on it.")
        # The model may run the project during the turn, so the chart it draws has to be
        # measured against the project as it was before the turn started.
        self._note_images()
        self._note_milestone()

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
        self.working("")
        self.set_model_status("ready", "Ready")
        for _name, result in turn.tool_results:
            if result.run is not None:
                self._show_run(result)
        if turn.text:
            self._say(ASSISTANT_NAME, turn.text)
        self.refresh_files()
        # A page already on screen is stale the moment a file changes, and a child who
        # has to press Preview again to find out whether the change worked will read the
        # old page as the new one. Only reloads what is already showing.
        if self._web is not None and turn.checkpoint is not None:
            self._web.reload()
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
        # Gary, not Open Nest: brand guide section 22's "Undo" example is his
        # ("Restored the version from before we changed the car speed."). Undo is a move
        # in the project the two of them are making, not installation or account
        # machinery, so it falls on Gary's side of the split.
        if restored is None:
            self._say(ASSISTANT_NAME, "There is no earlier version to go back to.")
            return
        self.refresh_files()
        self._refresh_undo()
        self.controller.refresh_state()
        self._panel_text("")
        self._say(ASSISTANT_NAME, f"Went back to: {restored.label}")

    def _turn_failed(self, message: str) -> None:
        """A turn that never produced a reply -- so nobody said anything.

        Attributed to Open Nest rather than to Gary, and that is the substantive half of
        the split rather than a rename. What arrives here is a ``ProviderError`` from
        ``AgentWorker``: the model would not load, the service refused the key, the call
        budget ran out. Putting Gary's name on a transport failure would have him
        announce a fault in the machinery he speaks through, which is exactly the
        pretending PHASE_10_HANDOFF.md section 1 rules out.
        """
        self._busy(False)
        self.working("")
        self.set_model_status("attention", "Problem")
        self._say(SYSTEM_NAME, message)

    def _show_run(self, result) -> None:
        run = result.run
        self._clear_details()
        self._mark_first_success(run)
        if run.still_running:
            # Not "close its window": a Raspberry Pi test loop is a console program and
            # has no window to close. Stop is true for both, and it is right there.
            self._output.setPlainText("The project is running. Press Stop when you are done.")
            self._stop_button.setEnabled(True)
            return
        if run.ok:
            self._output.setPlainText(run.stdout or "(no output)")
        else:
            self._technical_detail = run.failure_text
            self._headline = headline_failure(run)
            self._output.setPlainText(self._headline)
            self._details_button.setVisible(bool(run.failure_text.strip()))
        self._show_any_chart()

    # -- section 30's technical detail --------------------------------------

    def _panel_text(self, text: str) -> None:
        """Show something in the Build / Preview panel that is not a run failure.

        Everything except the failure display goes through here, so a Show technical
        details button can never be left over a file listing or a later message with the
        stderr of some earlier run behind it.
        """
        self._clear_details()
        self._output.setPlainText(text)

    def _clear_details(self) -> None:
        self._technical_detail = ""
        self._headline = ""
        self._details_shown = False
        self._details_button.hide()
        self._details_button.setText(SHOW_DETAILS)

    def _toggle_details(self) -> None:
        """Swap between the headline and the exact output. Nothing is thrown away."""
        self._details_shown = not self._details_shown
        if self._details_shown:
            self._output.setPlainText(self._technical_detail)
            self._details_button.setText(HIDE_DETAILS)
        else:
            self._output.setPlainText(self._headline)
            self._details_button.setText(SHOW_DETAILS)

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

    #: What the approval mark says when a project works for the first time.
    #:
    #: Guide section 38 offers "It works." and "You built that." for this moment, and the
    #: second is the one that is true in every case here. ``RunResult.ok`` means
    #: different things per profile: a Research analysis ran to completion and exited 0,
    #: an Arduino sketch was accepted by the compiler, and a *game* survived a
    #: four-second startup grace and is on screen. That last one is not evidence the game
    #: works, so putting "It works." under it would claim a state nothing verified.
    #: "You built that." is about authorship rather than machine state, so it over-claims
    #: nothing -- and what *was* verified is already in the Build / Preview panel beside
    #: it, which is section 46's "never the only signal".
    FIRST_SUCCESS = "You built that."

    def _mark_first_success(self, run) -> None:
        """The one thing in the Workbench that earns the approval mark.

        Fires at most once in a project's life: the first run that worked, **of a project
        the child has actually changed**. Not every run, not every save, not every
        checkpoint -- section 39 lists those explicitly as what the sunglasses are not
        for, and the graphic only keeps its meaning while it stays rare. Reopening a
        project that already works shows nothing, because the manifest remembers.

        The "has actually changed" half was missing and the owner caught it watching a
        Phase 12.2 walk. The chain was: the model calls ``run_project`` itself during its
        first turn, the untouched starter launches, ``RunResult.ok`` is True for an
        interactive project the moment it survives four seconds -- and Open Nest awarded
        the approval mark and **"You built that."** for an orange square on a black
        background that it had shipped itself. The child had built nothing and had not
        even pressed Run.

        The copy was already chosen to avoid claiming machine state (see
        :attr:`FIRST_SUCCESS`), which is why this read as defensible. It is not: for a
        starter that has never been edited, *authorship* is the part that is false. This
        is the same over-claim Phase 12.1 removed from Gary's mouth, in the
        application's own voice.

        ``can_undo`` is the deterministic test, and it is exact rather than a proxy:
        ``VersionHistory.start`` commits ``LABEL_CREATED`` when the project is made, and
        ``save`` only commits when something actually changed, so a second checkpoint
        existing *is* "this project has diverged from the kit it began as".
        """
        if not run.ok or self._worked_before or not self._child_has_changed_anything():
            return
        self._worked_before = True
        self.completed(self.FIRST_SUCCESS)

    def _child_has_changed_anything(self) -> bool:
        """Whether this project is still exactly the starter it was created from.

        Without versioning there is nothing to compare against. That case keeps the old
        behaviour rather than withdrawing the milestone from a machine with no git: a
        mark shown slightly too eagerly is a smaller fault than a feature that silently
        disappears, and every supported installation has git.
        """
        if self.versions is None or not self.versions.enabled:
            return True
        return self.versions.can_undo

    def _note_milestone(self) -> None:
        """Remember whether this project had *ever* worked, before this run changes it.

        ``Toolbox`` stamps ``manifest.last_successful_run`` the moment a run succeeds,
        so by the time the result reaches the panel the field is already set and the
        "was this the first time?" question can no longer be asked. Captured here for
        the same reason the picture snapshot is: the answer only exists beforehand.

        Monotonic on purpose. Re-reading the manifest each time would let the flag go
        *back* to False, and then a second successful run would award the milestone
        again -- ``_record_success`` saves under ``contextlib.suppress(OSError)``, so a
        manifest that could not be written is a real path to exactly that. Once a
        project has worked it has worked, and nothing here can un-learn it.
        """
        self._worked_before = self._worked_before or bool(
            self.project.manifest.last_successful_run
        )

    def _run(self) -> None:
        """The main button: run, compile, preview or generate, depending on the profile.

        This used to always dispatch ``run_project``. On an Arduino project, which has no
        run command and no such tool, that showed the child a message written for the
        model: "'run_project' is not available here. You can use: read_file, ...".
        """
        profile = self.project.profile
        if profile.generates:
            self._generate_image()
            return
        if profile.previews:
            self._preview()
            return
        if not self._something_to_run():
            return

        self._note_images()
        self._note_milestone()
        tool = "run_project" if profile.can_run else "compile_project"
        result = self.toolbox.dispatch(tool, {})
        if result.run is not None:
            self._show_run(result)
        elif not result.ok:
            self._panel_text(result.content)

    def _something_to_run(self) -> bool:
        """Whether the entry point exists yet, said plainly when it does not.

        A project started empty has no ``src/main.py``, and pressing Run would otherwise
        show the interpreter's own "No such file or directory" -- a message about a path
        a child never chose. Starting empty is a supported choice, so its first press of
        Run has to be answered like one.
        """
        if self.project.entrypoint_path.is_file():
            return True
        offer = (
            f" Add a starter from the Project panel, or tell {ASSISTANT_NAME} what to make."
            if self._starter_buttons
            else f" Tell {ASSISTANT_NAME} what you want to make and it will be written."
        )
        self._panel_text(
            f"There is nothing to run yet -- this project has no "
            f"src/{self.project.manifest.entrypoint}.{offer}"
        )
        return False

    def _preview(self) -> None:
        """Show the page. A website is opened, never executed.

        No process starts, so there is nothing for the process sandbox to confine; the
        boundary is :mod:`opennest.execution.web_preview`, which refuses every request
        the page makes that is not a file inside this project.
        """
        if self._web is None:
            return
        if not web_preview.is_previewable(self.project):
            self._something_to_run()
            return
        # Said before the render, not after. Chromium drops a remote request from a
        # file: page before anything Open Nest installed is consulted (SPIKES.md section
        # 19), so without this the only symptom is a picture that is not there.
        self._panel_text(
            web_preview.remote_warning(web_preview.remote_references(self.project))
        )
        self._web.show_page(web_preview.entry_url(self.project))

    def _save_version(self) -> None:
        """Mark the project as it is now, by hand.

        Gary's voice, because a saved version is a move in the project the two of them
        are making rather than installation or account machinery -- the same split that
        puts Undo on his side (brand guide section 22).

        "Nothing to save" is a real and common answer: autosave has usually already
        taken it, and saying so is better than an identical second version or a silent
        button. The label is the child's own words for the thing, not a commit message.
        """
        if self.versions is None:
            return
        try:
            saved = self.versions.save(LABEL_SAVED_BY_HAND)
        except SecretsFound as exc:
            QMessageBox.warning(self, "Open Nest", str(exc))
            return
        except GitError as exc:
            QMessageBox.warning(self, "Open Nest", str(exc))
            return
        self._refresh_undo()
        if saved is None:
            self._say(ASSISTANT_NAME,
                      "Nothing has changed since the last saved version, so there is "
                      "nothing new to save.")
        else:
            self._say(ASSISTANT_NAME, "Saved. You can come back to this version.")

    def _stop(self) -> None:
        if self.toolbox.last_run is not None:
            stop_project(self.toolbox.last_run)
        self._stop_button.setEnabled(False)
        self._panel_text("Stopped.")

    def release(self) -> None:
        """Let go of anything that has to be torn down in a particular order.

        Two things: the web engine, whose page has to be let go of before the profile
        that owns it, and any worker thread still running. A widget destroyed while one
        of its threads is alive aborts the interpreter rather than raising -- see
        ``ui.worker.stop_thread``.

        Closing a parent widget does not call ``closeEvent`` on its children, so this is
        called explicitly when a project closes rather than left to Qt.
        """
        stop_thread(self._thread)
        self._thread = None
        # And a game still on screen. Closing the project left the child process
        # running with its own window: nothing owned it any more, Stop was gone with
        # the Workbench, and the only way to be rid of it was to quit the game itself.
        if self.toolbox.last_run is not None:
            stop_project(self.toolbox.last_run)
        if self._web is not None:
            self._web.close()

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
            self._panel_text("Choose which Arduino you have first.")
            return

        try:
            ports = arduino.connected_ports()
        except arduino.ArduinoUnavailable as exc:
            self._panel_text(str(exc))
            return

        recognised = [port for port in ports if port.board is not None] or ports
        if not recognised:
            self._panel_text(
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
            self._panel_text("A parent has not allowed sending to a board.")
            return

        self._panel_text(f"Sending to {port.label}…")
        try:
            result = arduino.upload(self.project, board, port.address)
        except arduino.ArduinoUnavailable as exc:
            self._panel_text(str(exc))
            return
        if result.ok:
            self._panel_text(f"Sent to {port.label}.\n\n{result.stdout.strip()}")
        else:
            self._panel_text(result.failure_text or "Sending to the board failed.")

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
            self._panel_text(unmet)
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
        self.working("Making your picture.")
        self._panel_text("Making your picture. This takes about fifteen seconds…")
        self._say("You", f"Make a picture: {description}")

        worker = ImageWorker(self.project, description, credentials=self.credentials)
        worker.finished.connect(self._image_ready)
        worker.failed.connect(self._image_failed)
        self._thread = run_in_thread(self, worker)
        self._thread.finished.connect(self._thread_done)

    def _image_ready(self, asset) -> None:
        self._busy(False)
        self.working("")
        self._show_any_chart(asset.path)
        self.refresh_files()
        # Section 13's rule, kept at the point a picture appears: Open Nest asked for
        # this image and saved it, and still has not looked at it. Gary says it, and the
        # sentence itself is unchanged -- the honesty content is load-bearing
        # (HANDOFF section 6C) and does not become warmer because he is the one saying it.
        self._say(
            ASSISTANT_NAME,
            f"Saved as {asset.path}. {asset.summary}\n"
            f"  Nothing has looked at the picture itself -- open it to see how it came out.",
        )

    def _image_failed(self, message: str) -> None:
        self._busy(False)
        self.working("")
        self._panel_text(message)
