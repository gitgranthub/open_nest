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

import contextlib
import subprocess
from pathlib import Path

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPixmap, QTextCursor, QTextFormat
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
    QStyledItemDelegate,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from opennest import ASSISTANT_NAME, SYSTEM_NAME
from opennest.agent.controller import AgentController
from opennest.agent.tools import Step, Toolbox
from opennest.ai import images
from opennest.ai.router import models_for_project, models_that_can_read, why_unavailable
from opennest.assets import kinds
from opennest.assets import manager as assets
from opennest.execution import arduino, outputs, web_preview
from opennest.execution.python_runner import finished, stop_project
from opennest.projects import starters
from opennest.projects.manager import (
    MANIFEST_NAME,
    Project,
    ProjectError,
    add_starter,
    plays_in_panel,
    source_fingerprint,
)
from opennest.security.sandbox import visible_files
from opennest.ui import about_gary, brand, theme
from opennest.ui import web_preview as web_preview_ui
from opennest.ui.common import horizontal_rule, section_label, status_row
from opennest.ui.game_view import GameView
from opennest.ui.game_window import GameWindow
from opennest.ui.worker import (
    AgentWorker,
    ImageWorker,
    RunWorker,
    run_in_thread,
    stop_thread,
    wait_for_thread,
)
from opennest.versioning.checkpoint import LABEL_SAVED_BY_HAND, VersionHistory
from opennest.versioning.git_manager import GitError, SecretsFound

#: WORKORDER_01 section 30's control, in the words it uses. DESIGN_DOC section 12's
#: button language asks for the verb the child believes in, and "Show Details" is on its
#: own list of good labels.
SHOW_DETAILS = "Show technical details"
HIDE_DETAILS = "Hide technical details"
#: After a turn that changed code and then ran it, the panel shows the result and this
#: swaps to the code (and back), so every project type ends with both one click apart.
SHOW_CODE = "Show the code that changed"
SHOW_RESULT = "Show the result"
#: After clicking a file while the game plays: back to the game, which kept running.
SHOW_GAME = "Show the game"
#: Phase 13B's one button, in its two states.
POP_OUT = "Pop out"
PUT_BACK = "Put back"
#: ...and while a website's page is showing: back to the page.
SHOW_PAGE = "Show the page"

#: Where a file list item keeps its mark: "new" or "changed" since the child's last message.
MARK_ROLE = Qt.ItemDataRole.UserRole + 1
MARK_WORDS = {"new": "\u25cf new", "changed": "\u25cf changed"}


class MarkDelegate(QStyledItemDelegate):
    """A file's name as usual, and -- when the last message changed it -- a small dot and
    one word beside it in the palette's muted green (brand guide section 25: green is for
    quiet technical state, never a large or bright block). Painted rather than put in the
    item's text, so the name a child reads and clicks stays the file's own name."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        mark = index.data(MARK_ROLE)
        if mark not in MARK_WORDS:
            return
        painter.save()
        font = painter.font()
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 8.0))
        painter.setFont(font)
        painter.setPen(QColor(theme.resolve_palette().ok))
        area = QRect(option.rect)
        area.setRight(area.right() - 6)
        painter.drawText(area, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                         MARK_WORDS[mark])
        painter.restore()


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
        #: Set by :meth:`release`: the project is closing, and a turn that ends now is
        #: not shown -- its work is kept, and the Workbench is on its way out.
        self._releasing = False
        #: The run whose pictures the game view is showing, or None. Phase 13.
        self._live_run = None
        #: That game's own window title, which it has no window to show.
        self._live_title = ""
        #: What the child's last message changed, by project-relative path: the last
        #: ``changed`` step for each file. Marked in the Project panel and used when a file
        #: is clicked, until the next message or an Undo.
        self._recent: dict[str, Step] = {}
        #: The project's code and pictures as they were when that game started, so a
        #: game left playing after a change is known to be the old version.
        self._live_files: tuple = ()
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
        self._marks = MarkDelegate(self)
        self._files = QListWidget()
        self._files.setItemDelegate(self._marks)
        # One click shows a file's code in Build / Preview -- the chat no longer carries it.
        self._files.itemClicked.connect(self._open_file)
        self._files.itemActivated.connect(self._open_file)
        layout.addWidget(self._files, 2)

        layout.addWidget(section_label("Assets"))
        self._assets = QListWidget()
        self._assets.setItemDelegate(self._marks)
        self._assets.itemClicked.connect(self._describe_asset)
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

        # The child's game, drawn here rather than in a window of its own (Phase 13).
        # Hidden until a game is running, so the panel is unchanged until then.
        self._game = None
        self._game_title = QLabel()
        self._game_title.setProperty("role", "mono")
        self._game_title.hide()
        # Phase 13B: the same game, in a window of its own and back (``GameWindow``).
        self._pop_button = QPushButton(POP_OUT)
        self._pop_button.setToolTip("Play the game in a window of its own -- it keeps "
                                    "playing, and Put back brings it home")
        self._pop_button.clicked.connect(self._toggle_pop)
        self._pop_button.hide()
        title_row = QHBoxLayout()
        title_row.addWidget(self._game_title, 1)
        title_row.addWidget(self._pop_button)
        layout.addLayout(title_row)
        self._popped_note = QLabel("Your game is playing in its own window. Put back "
                                   "brings it here.")
        self._popped_note.setProperty("role", "cardBody")
        self._popped_note.setWordWrap(True)
        self._popped_note.hide()
        layout.addWidget(self._popped_note)
        #: The window the game is in while popped out, made the first time it is needed.
        self._game_window: GameWindow | None = None
        # A Blank project can become a game (the owner-test pass), so it has the view too.
        if self.project.profile.live_view or (self.project.profile.id == "blank"
                                              and self.project.profile.can_run):
            self._game = GameView(self)
            self._game.hide()
            self._game.ended.connect(self._game_ended)
            self._game.focus_changed.connect(self._game_focus)
            self._game.title_changed.connect(self._game_titled)
            #: Where the game lives in the panel, to put it back exactly there.
            self._game_home = (layout, layout.count())
            layout.addWidget(self._game, 3)

        # Which file the code below is, while a turn is building it (``_show_code``).
        self._code_caption = QLabel()
        self._code_caption.setProperty("role", "mono")
        self._code_caption.hide()
        layout.addWidget(self._code_caption)

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
        self._code_button = QPushButton(SHOW_CODE)
        self._code_button.setToolTip("Switch between the code this turn changed and what "
                                     "running it showed")
        self._code_button.clicked.connect(self._toggle_code)
        self._code_button.hide()
        #: This turn's last changed file, and the result view a run left, for the toggle.
        self._turn_code = None
        self._run_view = None
        details_row = QHBoxLayout()
        details_row.addWidget(self._details_button)
        details_row.addWidget(self._code_button)
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

        # No approval mark here. The white sunglasses are reserved for a child
        # publishing a version (brand guide section 38, as ruled in Phase 13): not a
        # run, a recipe, a playtest, a turn, a checkpoint or a compile. Routine success
        # is said in text and status, and nothing in the Workbench shows them today.

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
            item = QListWidgetItem(name)
            self._mark(item, name)
            self._files.addItem(item)

        self._assets.clear()
        for asset in imported:
            item = QListWidgetItem(asset.name)
            item.setData(Qt.ItemDataRole.UserRole, asset)
            item.setToolTip(asset.summary)
            self._mark(item, asset.path, tooltip=asset.summary)
            self._assets.addItem(item)

        self._refresh_starter_offer()

    def _mark(self, item: QListWidgetItem, path: str, *, tooltip: str = "") -> None:
        """New or changed since the child's last message: said beside the file, quietly."""
        step = self._recent.get(path)
        if step is None:
            return
        mark = "new" if step.created else "changed"
        item.setData(MARK_ROLE, mark)
        said = f"{'New' if mark == 'new' else 'Changed'} in your last message"
        item.setToolTip(f"{tooltip}\n{said}" if tooltip else said)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{item.text()}, {mark}")

    def _refresh_starter_offer(self) -> None:
        """Show "nothing here yet" and the starter buttons, or neither.

        The offer disappears the moment there is a file, which is the whole safety
        argument for it being one click: it is only ever offered into an empty project.
        """
        empty = not starters.has_own_files(self.project.directory / "src")
        offered = bool(self._starter_buttons) and empty
        if empty:
            # No file names and no "starter" as a thing to understand: asking is enough,
            # because the first request sets the starting files up (the owner-test pass).
            self._empty_note.setText(
                f"Nothing here yet.\nTell {ASSISTANT_NAME} what you want to make, and the "
                f"starting files are set up first. Or add them now:"
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
        for name in written:
            relative = f"src/{name}"
            content = self._text_of(relative)
            if content is not None:
                self._recent[relative] = Step("changed", f"created {relative}", path=relative,
                                              content=content, created=True)
        self.refresh_files()
        # The model is told what it now has, the same way it is told after any other
        # change to the project -- and that it changed outside a message, so a plan
        # waiting for "next" is checked against it. Gary knowing which foundation exists
        # is the point of recording the starter at all.
        name = starters.get_starter(starter_id).name
        self.controller.note_outside_change(
            f"The {name} starter was added from the Project panel")
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

    def _text_of(self, relative: str) -> str | None:
        try:
            return (self.project.directory / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _open_file(self, item: QListWidgetItem) -> None:
        """A file's code in Build / Preview, with what the last message changed marked.

        The code belongs here, not in the chat: Gary says what he did, and this is where
        the child can see it. The marks are only the last message's -- and only while the
        file still reads as it did then, so an edit since cannot put them on the wrong
        lines. A game playing in the panel keeps playing; "Show the game" brings it back.
        """
        relative = item.text()
        if Path(relative).suffix.lower() in outputs.IMAGE_SUFFIXES:
            # A chart a run drew, or any picture: shown, not refused as "not text".
            self._panel_text("")
            self._show_any_chart(relative)
            return
        content = self._text_of(relative)
        if content is None:
            self._panel_text(f"{relative} is not a text file.")
            return
        recent = self._recent.get(relative)
        current = recent is not None and recent.content == content
        game_showing = self._game is not None and self._live_run is not None and \
            not self._popped and not self._game.isHidden()
        page_showing = self._web is not None and not self._web.isHidden()
        if game_showing or page_showing:
            self._run_view = (self._output.toPlainText(), "", "", False)
        self._show_code(Step("file", "", path=relative, content=content,
                             changed_lines=recent.changed_lines if current else (),
                             created=bool(current and recent.created)))
        if game_showing or page_showing:
            self._code_button.setText(SHOW_GAME if game_showing else SHOW_PAGE)
            self._code_button.show()

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

        # WORKORDER_01 section 29A's PR policy branches *before* the change, the way its
        # own diagram does. Off by default, so this is "" for a normal child session.
        self._review_branch = self._begin_review_branch()

        self._last_step = ""
        self._turn_code = self._run_view = None
        self._code_button.hide()
        # The marks are "changed since your last message": this one starts afresh.
        self._recent = {}
        self.refresh_files()
        worker = AgentWorker(self.controller, text, attachments)
        worker.progress.connect(self._progress)
        worker.finished.connect(self._turn_finished)
        worker.failed.connect(self._turn_failed)
        self._thread = run_in_thread(self, worker)
        self._thread.finished.connect(self._thread_done)

    def _thread_done(self) -> None:
        self._thread = None

    def _turn_finished(self, turn) -> None:
        if self._releasing:
            return
        self._busy(False)
        self.working("")
        for _name, result in turn.tool_results:
            # A game Gary started this turn, so it can be judged like any other.
            if result.run is not None and result.run.live is not None \
                    and result.run.still_running:
                self._live_run = result.run
        if turn.checkpoint is not None:
            self._retire_game_if_stale()
        self._page_back()
        self.set_model_status("ready", "Ready")
        for _name, result in turn.tool_results:
            if result.run is not None:
                self._show_run(result)
        self._show_still(turn)
        if self._turn_code is not None and self._run_view is not None:
            # A run replaced the code on screen at the end: the result stays first, and
            # the code that changed is one click away -- in every project type alike.
            self._code_button.setText(SHOW_CODE)
            self._code_button.show()
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
        # The game on screen may be the version that was just undone.
        self._retire_game_if_stale()
        # The marks said what the last message changed; after an Undo that is not true.
        self._recent = {}
        self.refresh_files()
        self._refresh_undo()
        # Gary is told, and a plan waiting for "next" is checked against it: the owner's
        # test found a plan carrying on as if nothing underneath it had moved.
        self.controller.note_outside_change(
            f"Undo went back to the version saved as \u201c{restored.label}\u201d",
            undone=True)
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
        if self._releasing:
            return
        self._busy(False)
        self.working("")
        self._page_back()
        self.set_model_status("attention", "Problem")
        self._say(SYSTEM_NAME, message)

    def _show_run(self, result) -> None:
        run = result.run
        self._clear_details()
        self._clear_code_marks()
        if run.still_running and run.output is not None and run.output.stopped:
            # Stopped already -- by Stop, by a newer run, or because the files changed
            # under it. Whatever stopped it has said so.
            return
        if run.still_running and run.live is not None and self._game is not None:
            self._show_game(run)
            self._run_view = (self._output.toPlainText(), "", "", False)
            return
        if self._game is not None and self._game.stream is not None \
                and self._game.stream is not getattr(self._live_run, "live", None):
            # Its pictures were showing from the start, and it fell over during the
            # startup check: the failure below is the thing to read now.
            self._put_back()
            self._game.detach()
            self._game.hide()
            self._game_title.hide()
            self._refresh_game_caption()
        if run.still_running:
            # Not "close its window": a Raspberry Pi test loop is a console program and
            # has no window to close. Stop is true for both, and it is right there.
            self._output.setPlainText("The project is running. Press Stop when you are done.")
            self._stop_button.setEnabled(True)
            return
        if run.ok and self.project.profile.can_compile:
            # What a compile shows and what it does not: nothing is known about a board.
            self._output.setPlainText(
                "It compiles. That checks the code; Send to Board puts it on your Arduino."
                f"\n\n{run.stdout.strip()}")
        elif run.ok:
            self._output.setPlainText(run.stdout or "(no output)")
        else:
            self._show_failure(run)
        self._run_view = (self._output.toPlainText(), self._technical_detail, self._headline,
                          not self._details_button.isHidden())
        self._show_any_chart()

    def _show_failure(self, run) -> None:
        """Section 30: the one line worth leading with, the rest behind a button."""
        self._technical_detail = run.failure_text
        self._headline = headline_failure(run)
        self._output.setPlainText(self._headline)
        self._details_button.setVisible(bool(run.failure_text.strip()))

    # -- the game, drawn here (Phase 13) --------------------------------------

    def _show_game(self, run) -> None:
        """Put a running game in the panel, once its run has reported. Idempotent."""
        self._live_run = run
        self._show_game_stream(run.live)
        self._output.setPlainText("Your game is running here. Press Stop when you are done.")
        self._stop_button.setEnabled(True)

    def _show_game_stream(self, stream) -> None:
        """Show a game's pictures -- from the moment it starts, before its run reports.

        The run's result arrives only after the four-second startup check, and the
        pictures should not wait for it. Attaching the same stream twice is not a
        restart, so the result arriving later changes nothing on screen.
        """
        if self._game.stream is not stream:
            # Cleared first: attaching delivers the game's title straight away.
            self._live_title = ""
            self._live_files = source_fingerprint(self.project.directory)
            self._game.attach(stream)
        self._chart.hide()
        self._chart_caption.hide()
        self._code_caption.hide()
        if not self._popped:
            self._game.show()
            self._output.setMaximumHeight(110)
        self._game_title.show()
        self._refresh_game_caption()

    def _refresh_game_caption(self) -> None:
        if self._game is None:
            return
        title = self._live_title or self.project.name
        if not self._game.running:
            hint = ""
        elif self._game.hasFocus():
            hint = "playing -- press Tab to leave the game"
        else:
            hint = "click the game to play"
        self._game_title.setText(f"{title}   \u00b7   {hint}" if hint else title)
        attached = self._game.stream is not None
        self._pop_button.setVisible(attached and (self._popped or not self._game.isHidden()))
        self._pop_button.setText(PUT_BACK if self._popped else POP_OUT)
        self._popped_note.setVisible(self._popped)
        if self._popped:
            self._game_window.caption.setText(f"{title}   \u00b7   {hint}" if hint else title)
            self._game_window.set_title(f"{title} \u2014 {self.project.name}")

    def _game_focus(self, _focused: bool = False) -> None:
        self._refresh_game_caption()

    def _game_titled(self, title: str) -> None:
        # The game's own window title, which it no longer has a window to show -- so
        # "Call my game Eagle Patrol" is visible here instead. Plain text, and bounded,
        # by the time the stream hands it over.
        self._live_title = title
        self._refresh_game_caption()

    def _game_ended(self) -> None:
        """The game's pictures stopped. Say how it ended -- only what actually happened."""
        run = self._live_run
        if run is None or self._game is None:
            return
        stream = run.live
        process = run.process
        if process is not None and process.poll() is None and not stream.broken:
            # The pictures stop the moment the game's process goes; give it that moment.
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
        self._stop_button.setEnabled(False)
        idle = self._thread is None   # during a turn, the panel is showing Gary's work
        if process is not None and process.poll() is None:
            # The game is still going, and the stream is not: it sent something that is
            # not a picture, or closed the channel it was given. Nothing on screen would
            # be true any more, so it is stopped.
            stop_project(run)
            reason = stream.broken or "it stopped sending pictures"
            self._game.show_stopped("Stopped")
            if idle:
                self._panel_text(f"Open Nest stopped the game because {reason}.")
            return
        end = finished(run)
        if end is None or run.output.stopped:
            self._game.show_stopped("Stopped")
        elif end.ok:
            self._game.show_stopped("The game ended")
            if idle:
                self._panel_text("The game ended. Press Run Game to play it again.")
        else:
            self._game.show_stopped("The game stopped with an error")
            if idle:
                self._panel_text("")
                self._show_failure(end)
            # And Gary is told, next time he is asked anything: until now a crash
            # during play was never recorded, and his facts said "it is running now".
            if self.toolbox.last_run is run:
                self.toolbox.last_run = end
        self._refresh_game_caption()

    def _retire_game_if_stale(self) -> None:
        """Take the game out of the panel if it is not the version the files hold now.

        After a change or an Undo, a game still playing is the old one -- even one Gary
        started this turn, if he changed the code again afterwards. Left on screen it
        would read as the new version, which is exactly the kind of small claim this
        project does not let the application make. So it is stopped, and Run Game plays
        what is there now.
        """
        if self._game is None or self._game.stream is None:
            return
        if source_fingerprint(self.project.directory) == self._live_files:
            return
        run = self._live_run
        self._live_run = None
        self._put_back()
        self._game.detach()
        if run is not None and run.process is not None and run.process.poll() is None:
            stop_project(run)
        self._game.hide()
        self._game_title.hide()
        self._refresh_game_caption()
        self._stop_button.setEnabled(False)
        if self._web is None:
            self._output.setMaximumHeight(16777215)

    # -- pop out and put back (Phase 13B) -------------------------------------

    @property
    def _popped(self) -> bool:
        return self._game_window is not None and self._game_window.game is not None

    def _toggle_pop(self) -> None:
        if self._popped:
            self._put_back()
        else:
            self._pop_out()

    def _pop_out(self) -> None:
        """The same game widget, moved into a window of its own. Nothing restarts."""
        if self._game is None or self._game.stream is None or self._popped:
            return
        layout, _index = self._game_home
        layout.removeWidget(self._game)
        if self._game_window is None:
            self._game_window = GameWindow(self)
            self._game_window.put_back_requested.connect(self._put_back)
        title = self._live_title or self.project.name
        self._game_window.hold(self._game, f"{title} \u2014 {self.project.name}")
        if self._web is None:
            self._output.setMaximumHeight(16777215)
        if self._thread is None:
            self._output.setPlainText("Your game is in its own window. Press Stop when you "
                                      "are done, or Put back to bring it here.")
        self._refresh_game_caption()

    def _put_back(self) -> None:
        """Home again, where it was in the panel, still playing. Safe when not out."""
        if not self._popped:
            return
        game = self._game_window.give_back()
        layout, index = self._game_home
        layout.insertWidget(index, game, 3)
        game.setVisible(self._live_run is not None or game.stream is not None)
        self._output.setMaximumHeight(110)
        if self._thread is None and game.running:
            self._output.setPlainText("Your game is running here. Press Stop when you are "
                                      "done.")
        self._refresh_game_caption()

    # -- section 30's technical detail --------------------------------------

    def _panel_text(self, text: str) -> None:
        """Show something in the Build / Preview panel that is not a run failure.

        Everything except the failure display goes through here, so a Show technical
        details button can never be left over a file listing or a later message with the
        stderr of some earlier run behind it.
        """
        self._clear_details()
        self._clear_code_marks()
        self._code_button.hide()
        self._output.setPlainText(text)

    # -- the turn as it happens ---------------------------------------------

    def _progress(self, step) -> None:
        """One step of a turn, as Open Nest does it: a line in the chat, and the code.

        The steps are the application's own report of what it is doing (``tools.Step``)
        -- never Gary's words streamed as they arrive, which the honesty guard may yet
        replace. "changed" is not said in the chat, because "changing ..." already was;
        it puts the file, as it now is, in the Build / Preview panel instead.
        """
        if self._releasing:
            return
        if step.kind == "playing":
            # The game has started: show it now, not after the startup check. Said in
            # the chat already, as the "running the project" step before it.
            if self._game is not None and step.live is not None:
                self._show_game_stream(step.live)
            return
        if step.kind in ("changed", "undone") and step.content is not None:
            self._turn_code = step
            self._show_code(step)
            # The file appears in the Project panel as it is made, marked new or changed;
            # a recipe that puts one back leaves it unmarked, because nothing changed.
            if step.kind == "changed":
                earlier = self._recent.get(step.path)
                if earlier is not None and earlier.created:
                    step = Step("changed", step.text, path=step.path, content=step.content,
                                changed_lines=(), created=True)
                self._recent[step.path] = step
            else:
                self._recent.pop(step.path, None)
            self.refresh_files()
        if step.kind == "changed":
            return
        if step.kind in ("thinking", "recipe", "tool", "testing"):
            # Something he is doing now. A refusal or an undo is something that
            # happened, and "Gary is that change didn't fit" is not a sentence.
            self.working(f"{ASSISTANT_NAME} is {step.text}\u2026")
        if step.text != getattr(self, "_last_step", ""):
            self._last_step = step.text
            self._transcript.appendPlainText(f"   \u2026 {step.text}")

    def _show_code(self, step) -> None:
        """A file as it is right now, its new lines marked, scrolled to the first one."""
        if self._web is not None and not self._web.isHidden():
            # The page is about to change; while it is being built, the code is the thing
            # to watch. ``_page_back`` puts the page back when the turn ends.
            self._web.hide()
            self._output.setMaximumHeight(16777215)
        if self._game is not None and not self._popped and not self._game.isHidden():
            # The same for a game: the code is on screen while it is being changed. A
            # game in its own window stays there -- the code has the panel to itself.
            self._game.hide()
            self._game_title.hide()
            self._pop_button.hide()
            self._output.setMaximumHeight(16777215)
        self._panel_text(step.content)
        if step.kind == "undone":
            what = "put back as it was"
        elif step.created:
            what = "new file" if step.kind != "file" else "new in your last message"
        elif step.kind == "file" and not step.changed_lines:
            what = ""
        else:
            count = len(step.changed_lines)
            # A change that only took lines out leaves no new line to mark.
            what = (f"{count} line{'' if count == 1 else 's'} changed" if count
                    else "lines taken out")
            if step.kind == "file":
                what += " in your last message"
        self._code_caption.setText(f"{step.path} \u2014 {what}" if what else step.path)
        self._code_caption.show()
        colour = QColor(theme.resolve_palette().accent)
        colour.setAlpha(55)
        marks = []
        for line in step.changed_lines:
            block = self._output.document().findBlockByNumber(line)
            if not block.isValid():
                continue
            mark = QTextEdit.ExtraSelection()
            mark.format.setBackground(colour)
            mark.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            mark.cursor = QTextCursor(block)
            marks.append(mark)
        self._output.setExtraSelections(marks)
        if step.changed_lines:
            first = self._output.document().findBlockByNumber(step.changed_lines[0])
            if first.isValid():
                self._output.setTextCursor(QTextCursor(first))
                self._output.centerCursor()

    def _show_still(self, turn) -> None:
        """The last frame of the invisible test, after a turn that changed the game.

        A still, not the game: Run Game plays it, here in the panel (Phase 13). Only from
        a test that passed -- a picture of a game that crashed or froze would say it
        worked. Not over a game that is already playing: that is the better evidence.
        """
        tests = getattr(turn, "playtests", ())
        test = tests[-1] if tests else None
        if getattr(turn, "checkpoint", None) is None or test is None or not test.still:
            return
        if self._live_run is not None and self._game is not None and self._game.running:
            return
        self._show_any_chart(test.still)
        self._chart_caption.setText("How it looked when Open Nest tested it, with no "
                                    "window -- press Run Game to play it")

    def _toggle_code(self) -> None:
        """Swap between this turn's changed code and the result its run left."""
        if self._code_button.text() == SHOW_CODE and self._turn_code is not None:
            self._show_code(self._turn_code)
            self._code_button.setText(SHOW_RESULT)
            self._code_button.show()
        elif self._run_view is not None:
            text, detail, headline, has_details = self._run_view
            self._clear_details()
            self._clear_code_marks()
            self._output.setPlainText(text)
            self._technical_detail, self._headline = detail, headline
            self._details_button.setVisible(has_details)
            self._code_button.setText(SHOW_CODE)
            if self._turn_code is None:
                # Back from a file the child clicked: there is no turn's code to offer.
                self._code_button.hide()
            if self._live_run is not None and self._game is not None and not self._popped:
                self._game.show()
                self._game_title.show()
                self._output.setMaximumHeight(110)
                self._refresh_game_caption()
            if self._web is not None and self._web.isHidden():
                self._web.show()
                self._output.setMaximumHeight(110)

    def _clear_code_marks(self) -> None:
        self._code_caption.hide()
        self._output.setExtraSelections([])

    def _page_back(self) -> None:
        """After a turn, the page -- or the game -- goes back where it was, if code had
        taken its place."""
        if self._web is not None and self._web.isHidden():
            self._web.show()
            self._output.setMaximumHeight(110)
        if self._game is not None and self._live_run is not None and not self._popped \
                and self._game.isHidden():
            self._game.show()
            self._game_title.show()
            self._output.setMaximumHeight(110)
            self._refresh_game_caption()

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
        if profile.can_run and self._game is not None and plays_in_panel(self.project):
            self._start_game()
            return
        if profile.can_compile and arduino.available() and \
                not self.project.manifest.arduino_board:
            # The tool's own answer here is written for Gary ("Ask the child which
            # board..."); the parity walk showed it in the panel as it was.
            self._panel_text("Choose which Arduino you have first, in the list beside "
                             "Compile. Then press Compile again.")
            return
        tool = "run_project" if profile.can_run else "compile_project"
        result = self.toolbox.dispatch(tool, {})
        self._ran(result)
        self._tell_gary(result)

    def _ran(self, result) -> None:
        if result.run is not None:
            self._show_run(result)
        elif not result.ok:
            self._panel_text(result.content)

    def _tell_gary(self, result) -> None:
        """What the child's own press of the button did, for Gary next time.

        Measured on the parity walk: straight after the child pressed Run Analysis and
        a chart appeared, "why isn't this working?" was answered "No run was made"."""
        label = self.project.profile.run_label
        run = result.run
        if run is None or run.still_running:
            return
        if run.ok:
            drew = f" and drew {', '.join(result.made_files)}" if result.made_files else ""
            what = "compiled" if self.project.profile.can_compile else "ran"
            said = f"The child pressed {label}: it {what}{drew}."
        else:
            said = f"The child pressed {label}, and it failed (the error is in Last run)."
        with contextlib.suppress(Exception):
            self.controller.note_event(said, drew=bool(run.ok and result.made_files))

    def _start_game(self) -> None:
        """Run Game, for a game drawn here: started off the UI thread (``RunWorker``).

        The panel keeps painting through the four-second startup check, and the game's
        pictures appear the moment it has started. Sending a message waits until it has
        -- one project runs one thing at a time through its Toolbox.
        """
        if self._thread is not None:
            return
        self._busy(True)
        self._panel_text("Starting your game\u2026")
        worker = RunWorker(self.toolbox)
        worker.progress.connect(self._progress)
        worker.finished.connect(self._game_started)
        self._thread = run_in_thread(self, worker)
        self._thread.finished.connect(self._thread_done)

    def _game_started(self, result) -> None:
        if self._releasing:
            return
        self._busy(False)
        self._ran(result)
        if self._live_run is not None and self._live_run is result.run and self._game.running:
            # The child pressed Run Game, so the game is what they are about to use --
            # as a window of its own would have been. A run Gary starts never takes
            # the keyboard away from the chat.
            self._game.setFocus(Qt.FocusReason.OtherFocusReason)

    def _something_to_run(self) -> bool:
        """Whether the entry point exists yet, said plainly when it does not.

        A project started empty has no ``src/main.py``, and pressing Run would otherwise
        show the interpreter's own "No such file or directory" -- a message about a path
        a child never chose. Starting empty is a supported choice, so its first press of
        Run has to be answered like one.
        """
        if self.project.entrypoint_path.is_file():
            return True
        src = self.project.directory / "src"
        blank_page = self.project.profile.id == "blank" and any(
            next(src.rglob(pattern), None) is not None for pattern in ("*.html", "*.ino"))
        if blank_page:
            # A page or a sketch Gary wrote in a Blank project: kept, and not something
            # Blank can show or compile. Said, rather than "nothing to run" (parity walk).
            self._panel_text("This is a Blank project, so it can only run src/main.py. To see "
                             "a web page or compile a sketch, start a Website or Arduino "
                             "project from the Flight Deck.")
            return False
        # No file names: the owner-test pass found a child told about src/game.py and
        # left to discover the starter button. Asking Gary is enough -- the first request
        # sets the starting files up -- and the button is still there for a child who
        # wants it now.
        game = self.project.profile.playtest == "pygame"
        first = "There's no game here yet." if game else "There's nothing to run yet."
        offer = (
            f" Tell {ASSISTANT_NAME} what you'd like to make and the starting "
            f"{'game' if game else 'files'} will be set up first -- or add "
            f"{'it' if game else 'them'} now from the Project panel."
            if self._starter_buttons
            else f" Tell {ASSISTANT_NAME} what you want to make."
        )
        self._panel_text(f"{first}{offer}")
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
        # Code a file click put here gives the panel back to the page.
        self._web.show()
        self._output.setMaximumHeight(110)
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
        if self._game is not None and self._game.stream is not None:
            self._game.show_stopped("Stopped")
            self._refresh_game_caption()

    def release(self) -> None:
        """Let go of anything that has to be torn down in a particular order.

        Two things: the web engine, whose page has to be let go of before the profile
        that owns it, and any worker thread still running. A widget destroyed while one
        of its threads is alive aborts the interpreter rather than raising -- see
        ``ui.worker.stop_thread``.

        Closing a parent widget does not call ``closeEvent`` on its children, so this is
        called explicitly when a project closes rather than left to Qt.

        **A turn still running is stopped and waited for, never abandoned.** Quitting
        while Gary was writing used to give his thread five seconds, park it, and carry
        on -- and a parked thread still running at exit is destroyed by Qt, which aborts
        the process (SPIKES.md section 26I). Now the turn is told to stop at its next
        safe point and this waits until its thread has ended, keeping the window alive
        meanwhile. What the turn had already changed is kept and checkpointed.
        """
        self._releasing = True
        if self._thread is not None:
            self.setEnabled(False)          # nothing new starts while it winds down
            self.working("Finishing up before the project closes.")
            self.controller.stop()
            wait_for_thread(self._thread)
            self.working("")
        stop_thread(self._thread)
        self._thread = None
        # And a game still on screen. Closing the project left the child process
        # running with its own window: nothing owned it any more, Stop was gone with
        # the Workbench, and the only way to be rid of it was to quit the game itself.
        if self.toolbox.last_run is not None:
            stop_project(self.toolbox.last_run)
        if self._live_run is not None:
            stop_project(self._live_run)
        self._put_back()
        if self._game_window is not None:
            self._game_window.close()
        if self._game is not None:
            self._game.detach()
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
