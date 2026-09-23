"""The graphical setup wizard — WORKORDER_01 section 35A.

Nine steps: section 35A's eight, plus the Arduino toolchain (decision D7). Welcome,
About You, Local AI, Arduino, Optional Cloud AI, GitHub Backup, Parent Settings, Test
Setup, Finish. Started by ``bootstrap.py`` once the environment exists, and reachable
afterwards from Settings as "Run Setup Again".

    .venv/bin/python -m opennest.setup.wizard

Four decisions about how it is built:

**A step is an object with ``enter`` and ``leave``, not a branch in one long method.**
``leave`` returning False blocks Next, which is how a step refuses to be skipped over.
It also makes each step testable on its own: build it, set its fields, call ``leave``,
and look at what it wrote into the shared :class:`~opennest.setup.state.InstallationState`.

**Nothing slow happens on the UI thread.** A model download is gigabytes and a
verification loads a 4B model; both go through ``ui.worker.run_in_thread``, which is the
same plumbing the workbench uses for generation. Section 35A asks for a working Cancel
button, and a frozen window cannot have one.

**The wizard writes through the application's own code, never around it.** Keys go to
``security.keychain``, permissions to ``security.permissions``, the model download and
its verification to ``setup.downloader``, and the health check to ``setup.checks``. The
only thing this file owns is the order of the questions.

**It is the parent's wizard.** Section 35A says so, and it shows: the copy explains
cost, network and privacy in a sentence each, and every optional thing can be skipped
without the wizard implying something is broken.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opennest import APP_NAME, paths
from opennest.ai import router
from opennest.ai.provider import ProviderError
from opennest.models import compatibility, discovery
from opennest.models import machine as machine_service
from opennest.security import keychain, permissions
from opennest.setup import checks, downloader, toolchain
from opennest.setup.state import InstallationState
from opennest.ui import brand, consent, theme
from opennest.ui.common import horizontal_rule, section_label
from opennest.ui.worker import run_in_thread, stop_thread

#: The control that folds the model ladder away. Section 42: first-run setup shows a
#: very small set, and a parent who wants the rest can ask.
SHOW_OPTIONS = "Show other options"
HIDE_OPTIONS = "Hide other options"


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "cardBody")
    label.setWordWrap(True)
    return label


def _mono(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "mono")
    label.setWordWrap(True)
    return label


def _identity(dark: bool) -> QWidget:
    """The wordmark with the nest beneath it -- guide section 58's opening.

    The setup wizard is a product-level experience, so section 58 allows the full
    identity here more prominently than anywhere inside the app. This is also the first
    of the three moments that teach the visual language without explaining it: identity
    at the start, the eagle while the model installs, the approval mark at the end.
    """
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(6)
    column.addWidget(brand.placed("wizard_wordmark", dark=dark))
    # Decorative: the wordmark beside it already carries the accessible name, and
    # section 46 asks not to announce a repeat of the same identity.
    column.addWidget(brand.placed("wizard_nest", dark=dark, decorative=True))
    return holder


class _Activity(QWidget):
    """The eagle with the status line it belongs to (guide sections 36, 37, 46).

    Hidden until there is real work, and it can only be shown *with* text -- the graphic
    is never the only indication that something is happening. Section 53 is the rule
    about which waits qualify: everything driven from here is a download, an install or
    a real inference, all of them well past the "just do it" threshold.
    """

    def __init__(self, dark: bool) -> None:
        super().__init__()
        self.setProperty("role", "bare")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._eagle = brand.EagleActivityIndicator(self, size=brand.EAGLE_SETUP, dark=dark)
        self._text = _body("")
        row.addWidget(self._eagle, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._text, 1, Qt.AlignmentFlag.AlignVCenter)
        self.hide()

    def show_working(self, text: str) -> None:
        self._text.setText(text)
        self.show()
        self._eagle.start()

    def done(self) -> None:
        self._eagle.stop()
        self.hide()


def _field(layout: QVBoxLayout, caption: str, placeholder: str = "") -> QLineEdit:
    label = QLabel(caption)
    label.setProperty("role", "cardTitle")
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    layout.addWidget(label)
    layout.addWidget(edit)
    return edit


# --------------------------------------------------------------------------- steps

class Step(QWidget):
    """One page of the wizard."""

    #: Shown as the page heading.
    title = ""
    #: The label on the button that leaves this step.
    next_label = "Continue"

    def __init__(self, wizard: SetupWizard) -> None:
        super().__init__()
        self.wizard = wizard
        self.state = wizard.state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.body = layout
        self.build()

    def build(self) -> None:  # pragma: no cover - overridden by every step
        raise NotImplementedError

    def enter(self) -> None:
        """Called each time the step is shown. Refresh anything that can have changed."""

    def leave(self) -> bool:
        """Called when Continue is pressed. Return False to stay on this step."""
        return True

    def initial_focus(self) -> QWidget | None:
        """What the keyboard should be on when this step opens. None leaves it alone.

        Only steps with something to type into override this. A step whose page is all
        explanation should not steal focus onto an arbitrary button -- the footer's
        Continue is the default button, so Return already works from nowhere in
        particular.
        """
        return None


class WelcomeStep(Step):
    """Section 35A step 1, plus the "Installation environment" hardware summary."""

    title = "Welcome to Open Nest"
    next_label = "Get Started"

    def build(self) -> None:
        self.body.addWidget(_identity(theme.is_dark()))
        self.body.addSpacing(8)
        self.body.addWidget(_body(
            "Open Nest helps kids make games, robots, Arduino projects, research "
            "projects and pictures, with AI running on this Mac.\n\n"
            "Most of it works with no internet at all. Cloud AI is optional, and it is "
            "off until you turn it on.\n\n"
            "This setup is for a parent. It takes a few minutes."
        ))
        self.body.addWidget(horizontal_rule())
        self.body.addWidget(section_label("This Mac"))
        self._machine = _mono("Checking...")
        self.body.addWidget(self._machine)
        self._warning = _body("")
        self._warning.setProperty("state", "attention")
        self._warning.hide()
        self.body.addWidget(self._warning)
        self.body.addStretch(1)

    def enter(self) -> None:
        # One service owns this (Phase 11 work order section 23). The wizard used to
        # call the bootstrap's detection here and the model step used nothing at all,
        # which is exactly the scattering that section forbids.
        machine = machine_service.detect()
        self._machine.setText(machine.summary())
        problems = machine_service.problems(machine)
        if problems:
            # A warning, never a refusal. Section 35A says "warn if the computer does
            # not meet supported requirements" -- an unsupported Mac is not always a
            # broken one, and the parent is the one who gets to decide.
            self._warning.setText("\n\n".join(problems))
            self._warning.show()
        else:
            self._warning.hide()


class IdentityStep(Step):
    """Section 35A step 2. The child-facing name and the Git identity are separate."""

    title = "Who will use Open Nest?"

    def build(self) -> None:
        self.body.addWidget(_body(
            "The display name is what Open Nest calls the child. The Git details go on "
            "saved versions of their projects."
        ))
        self._name = _field(self.body, "Name", "Elliot")
        self.body.addWidget(horizontal_rule())
        self.body.addWidget(_body(
            "Open Nest saves a version of a project every time something works. These "
            "names go on those saved versions, and only on projects Open Nest makes."
        ))
        self._git_name = _field(self.body, "Name on saved versions", "Elliot")
        self._git_email = _field(self.body, "Email on saved versions (optional)",
                                 "elliot@example.com")
        self.body.addWidget(_body(
            "You can leave the email blank. Open Nest still saves versions locally."
        ))
        self.body.addStretch(1)

    def enter(self) -> None:
        self._name.setText(self.state.child_name)
        self._git_name.setText(self.state.git_author_name or self.state.child_name)
        self._git_email.setText(self.state.git_author_email)

    def initial_focus(self) -> QWidget | None:
        """The one required field in the whole wizard."""
        return self._name

    def leave(self) -> bool:
        name = self._name.text().strip()
        if not name:
            self.wizard.complain("Open Nest needs a name to call the child.")
            return False
        self.state.child_name = name
        # Falling back to the display name keeps a saved version attributable when a
        # parent skips the Git fields, which section 35A explicitly allows.
        self.state.git_author_name = self._git_name.text().strip() or name
        self.state.git_author_email = self._git_email.text().strip()
        return True


class LocalAIStep(Step):
    """Sections 35A steps 3, "Model installation" and "Model verification".

    Phase 11B made this machine-aware, and the shape of the page follows from two rules
    that pull in opposite directions.

    Section 41 wants the step to *begin by detecting the computer* and recommend on what
    it finds. Section 56 wants the page not to become more technical as a result -- the
    complexity belongs underneath. So the page asks a question a parent already has
    ("what should I install?"), answers it in one sentence, and puts the ladder of
    alternatives behind a control nobody has to press.

    What is deliberately still on screen is the download size. Section 47 requires it
    before anything is fetched, and "calm" is not a reason to stop telling somebody that
    a thing is 17 GB.

    The inspection is real work off the GUI thread -- subprocesses for the hardware,
    every approved cache searched for an existing model -- which is what entitles this
    page to the eagle under guide sections 36 and 53.
    """

    title = "Local AI"

    def build(self) -> None:
        self.body.addWidget(_body(
            "Open Nest uses an AI model that runs on this Mac. Nothing a child types "
            "goes to the internet while they use it."
        ))

        # -- the answer, before the options --------------------------------
        self._headline = QLabel("")
        self._headline.setProperty("role", "cardTitle")
        self._headline.setWordWrap(True)
        self.body.addWidget(self._headline)
        self._detail = _body("")
        self.body.addWidget(self._detail)

        # -- everything else, folded away ----------------------------------
        self._more = QPushButton(SHOW_OPTIONS)
        self._more.clicked.connect(self._toggle_options)
        self._more.hide()
        # Offered rather than automatic. A family who has used Ollama, LM Studio or any
        # Hugging Face tool may already have gigabytes of models on this Mac, and
        # section 31 is about not downloading a second copy of something already here.
        self._find = QPushButton("Already have a model?")
        self._find.setToolTip("Look for AI models already on this Mac")
        self._find.clicked.connect(self._search_for_models)
        self._find.hide()
        more_row = QHBoxLayout()
        more_row.addWidget(self._more)
        more_row.addWidget(self._find)
        more_row.addStretch(1)
        self.body.addLayout(more_row)

        self._found = _body("")
        self._found.hide()
        self.body.addWidget(self._found)
        self._found_picker = QComboBox()
        self._found_picker.hide()
        self.body.addWidget(self._found_picker)
        self._use_found = QPushButton("Use This Model")
        self._use_found.clicked.connect(self._adopt_found)
        self._use_found.hide()
        found_row = QHBoxLayout()
        found_row.addWidget(self._use_found)
        found_row.addStretch(1)
        self.body.addLayout(found_row)

        self._picker = QComboBox()
        self._picker.hide()
        self.body.addWidget(self._picker)
        self._fit = _body("")
        self._fit.hide()
        self.body.addWidget(self._fit)

        self.body.addWidget(horizontal_rule())
        self._status = _body("")
        self.body.addWidget(self._status)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.hide()
        self.body.addWidget(self._bar)
        # Section 53's major-download tier is "eagle animation **plus** real progress
        # information", and "never replace useful numerical progress information with
        # animation alone". The bar and the byte counts above are untouched; the bird is
        # added beside them. It also covers the verification step, which is a real
        # inference and takes a couple of seconds with nothing to count.
        self._activity = _Activity(theme.is_dark())
        self.body.addWidget(self._activity)

        buttons = QHBoxLayout()
        self._install = QPushButton("Install")
        self._install.setProperty("role", "primary")
        self._install.clicked.connect(self._start)
        self._cancel = QPushButton("Cancel")
        self._cancel.clicked.connect(self._request_cancel)
        self._cancel.hide()
        buttons.addWidget(self._install)
        buttons.addWidget(self._cancel)
        buttons.addStretch(1)
        self.body.addLayout(buttons)

        self.body.addWidget(_body(
            "You can skip this for now. Open Nest then needs cloud AI to help with "
            "anything, and cloud AI costs money and uses the internet."
        ))
        self.body.addStretch(1)

        self._picker.currentIndexChanged.connect(self._model_changed)
        self._cancelled = False
        self._thread = None
        self._options_shown = False
        self._found_models: dict = {}
        #: Filled by the inspection. Until then there is nothing to recommend.
        self._machine = None
        self._verdicts: dict = {}
        self._installed: tuple = ()
        self._inspected = False
        #: The entry a download or verification is running for. Held here rather than
        #: captured in the signal's lambda -- see ``_start``.
        self._pending = None

    # -- looking at the Mac -------------------------------------------------

    def enter(self) -> None:
        """Section 41: begin by detecting the computer."""
        if self._inspected:
            self._describe()
            return
        self._begin_inspection()
        worker = _InspectWorker()
        worker.finished.connect(self._inspected_machine)
        self._thread = run_in_thread(self, worker)

    def inspect_now(self, machine=None) -> None:
        """Do the inspection on this thread, optionally for a Mac that is not this one.

        The seam the tests cut at, and it exists for a reason beyond convenience: the
        machine a developer happens to own must never be what decides whether a test
        passes. The target hardware is an 8 GB Mac and this was written on a 48 GB one,
        so every test of the recommendation behaviour hands in the machine it means.
        """
        self._begin_inspection()
        self._inspected_machine(inspect_machine(machine))

    def _begin_inspection(self) -> None:
        self._install.setEnabled(False)
        self._picker.setEnabled(False)
        self.wizard.set_busy(True)
        self._headline.setText("Checking this Mac…")
        self._detail.setText(
            "Open Nest is looking at how much memory and storage this Mac has, and "
            "whether a model is already installed."
        )
        # Indeterminate: there is nothing here to count, and a bar that invents a
        # percentage is the kind of small lie this project does not tell. The eagle is
        # what carries "something is happening"; the bar carries "and it is this page".
        self._bar.setRange(0, 0)
        self._bar.show()
        self._activity.show_working("Checking this Mac")

    def _inspected_machine(self, result) -> None:
        self._activity.done()
        self._bar.hide()
        self._bar.setRange(0, 100)
        self._machine, self._verdicts, self._installed = result
        self._inspected = True
        self._install.setEnabled(True)
        self._picker.setEnabled(True)
        self.wizard.set_busy(False)
        self._fill_picker()
        self._choose_suggestion()
        self._more.setVisible(self._picker.count() > 1)
        self._find.setVisible(True)
        self._describe()

    def _fill_picker(self) -> None:
        """Every model this Mac could actually install, best fit first.

        Section 25: a model known not to work here is not offered as a normal
        installation choice, so an ``incompatible`` verdict keeps it out of the list
        rather than putting it in greyed out. The reason a Mac cannot run anything at
        all is said once, above, instead of seven times.
        """
        self._picker.blockSignals(True)
        self._picker.clear()
        pairs = [
            (entry, self._verdicts[entry.info.id])
            for entry in router.local_models()
            if entry.info.id in self._verdicts
            and self._verdicts[entry.info.id].usable
        ]
        for entry, verdict in compatibility.sort_for_display(pairs):
            note = "Already installed" if verdict.installed else verdict.label
            self._picker.addItem(f"{entry.info.name} — {note}", entry.info.id)
        self._picker.blockSignals(False)

    def _choose_suggestion(self) -> None:
        """Select what Open Nest would pick, so the common path is pressing Install."""
        suggested = compatibility.suggestion(
            router.local_models(), self._machine,
            installed_ids=[m.model_id for m in self._installed],
        )
        # A model this parent already chose beats a fresh suggestion: they are running
        # setup again, not starting over.
        preferred = self.state.preferred_model
        wanted = preferred if preferred and self._picker.findData(preferred) >= 0 else (
            suggested[0].info.id if suggested else None
        )
        index = self._picker.findData(wanted) if wanted else -1
        self._picker.setCurrentIndex(max(0, index))

    # -- the chosen model ---------------------------------------------------

    def _entry(self):
        model_id = self._picker.currentData()
        return router.get_entry(model_id) if model_id else None

    def _describe(self) -> None:
        """Refresh the suggestion, the size line and the button.

        Deliberately not the status: ``_finish_attempt`` calls this, and an earlier
        version cleared the status here too -- which wiped "could not be downloaded" in
        the same instant it appeared. A failure a parent cannot read is a failure they
        will hit again.
        """
        entry = self._entry()
        if entry is None:
            self._headline.setText("No model can run on this Mac.")
            self._detail.setText(
                "Open Nest needs an Apple silicon Mac with at least 8 GB of memory. "
                "You can continue, and use cloud AI instead."
            )
            self._install.setEnabled(False)
            return

        verdict = self._verdicts.get(entry.info.id)
        installed = bool(verdict and verdict.installed)
        # Folded away, this is a suggestion. Opened up, it is whichever row they are
        # looking at, and calling that a suggestion would be Open Nest agreeing with
        # whatever was clicked last.
        self._headline.setText(
            entry.info.name if self._options_shown
            else f"Open Nest suggests {entry.info.name} for this Mac."
        )
        # Section 47: the size is stated before anything is downloaded, whatever else
        # the page is trying to keep quiet about.
        size = (
            "It is already on this Mac, so nothing will be downloaded."
            if installed else
            f"About {entry.download_gb:.1f} GB to download."
        )
        untested = compatibility.untested_note(entry, installed=installed)
        self._detail.setText(
            " ".join(part for part in (f"{entry.info.description}.", size, untested)
                     if part)
        )
        self._fit.setText(verdict.reason if verdict else "")
        self._install.setText("Check It Works" if installed else "Install")

    # -- models already on this Mac -----------------------------------------

    def _search_for_models(self) -> None:
        """Look for models a family already has, and say honestly what was found.

        Reading several caches off a disk is real work, so it gets the eagle and the
        button goes quiet while it runs -- guide section 36. It is fast enough that
        nobody will read the status line, which is fine: the line is there so the
        graphic is never the only thing saying something is happening.
        """
        self._find.setEnabled(False)
        self._activity.show_working("Looking for models on this Mac")
        try:
            found = discovery.search_local_models(router.load_catalogue())
        except Exception:
            found = ()
        finally:
            self._activity.done()
            self._find.setEnabled(True)
        self._show_found(found)

    def _show_found(self, found) -> None:
        usable = [item for item in found if item.can_attempt]
        blocked = [item for item in found if not item.can_attempt]

        self._found_picker.clear()
        self._found_models = {}
        for index, item in enumerate(usable):
            self._found_picker.addItem(f"{item.name} — {item.store}", index)
            self._found_models[index] = item
        self._found_picker.setVisible(bool(usable))
        self._use_found.setVisible(bool(usable))
        self._found.show()

        if not found:
            # The empty case, and the one most likely to leave somebody stuck. It offers
            # the two things that actually move them forward and names the third.
            self._found.setText(
                "No AI models were found on this Mac. You can download the suggested "
                "one above, or skip this step — Open Nest can use cloud AI instead, "
                "and you can add a local model later in Settings."
            )
            return

        lines = []
        if usable:
            lines.append(
                f"Found {len(usable)} model(s) already on this Mac that Open Nest "
                f"can use."
            )
        if blocked:
            # Listed rather than hidden. A parent who has models here and is told
            # "none found" will conclude the search is broken, and they would be right
            # to -- what is true is that these cannot be used, which is a different
            # thing and worth one sentence each.
            lines.append("These are on this Mac and Open Nest cannot use them:")
            lines.extend(f"  {item.name} — {item.reason}" for item in blocked[:5])
            if len(blocked) > 5:
                lines.append(f"  and {len(blocked) - 5} more.")
        if not usable:
            lines.append(
                "You can download the suggested model above, or skip this step."
            )
        self._found.setText("\n".join(lines))

    def _adopt_found(self) -> None:
        """Use a model that is already here, after checking it actually answers.

        Two things have to happen and the order matters.

        **A model outside Open Nest's own store is an explicit exception, so it is
        asked about.** Everything Open Nest downloads lives under ``OPENNEST_HOME`` and
        it loads from nowhere else by default -- that is the containment promise, and on
        a work-managed machine it is the point rather than a detail. Adopting a model
        from the standard Hugging Face cache widens that, and widening it silently to
        save a download would be trading the promise for convenience without telling
        anybody. So the parent is shown where the model is and agrees to it, and the
        path is written into ``installation.json`` where it can be seen and undone.

        **Only a catalogued model can be adopted in this release.** Open Nest has real
        metadata for those -- a context budget, a tool-calling capability, a memory
        requirement. For an unrecognised directory it has none of the three and would be
        guessing at all of them, which is the caution section 32 asks for. An
        unrecognised MLX model is reported as present and not offered: making it
        selectable needs somewhere for its metadata to come from, and that is a
        catalogue question rather than a detection one.
        """
        found = self._found_models.get(self._found_picker.currentData())
        if found is None or not found.model_id:
            return

        if not found.is_contained:
            allowed = self.wizard.confirm(
                "Use the model already on this Mac?",
                f"{found.name} is not in Open Nest's own folder. It is here:\n\n"
                f"{found.cache_root}\n\n"
                f"Open Nest normally only reads models it downloaded itself. Using this "
                f"one means it will also read from that folder. Nothing is copied or "
                f"moved, and you can undo this in Settings.",
            )
            if not allowed:
                return
            recorded = str(found.cache_root)
            if recorded not in self.state.extra_model_paths:
                self.state.extra_model_paths.append(recorded)

        index = self._picker.findData(found.model_id)
        if index >= 0:
            self._picker.setCurrentIndex(index)
        self._status.setText("")
        # Straight to the same real-inference check every other route uses. Nothing is
        # downloaded -- the model is here -- but "it is on disk" has never been allowed
        # to mean "it works" anywhere else in this file and does not start now.
        self._install.setEnabled(False)
        self._picker.setEnabled(False)
        self.wizard.set_busy(True)
        self._verify(router.get_entry(found.model_id))

    def _toggle_options(self) -> None:
        """Section 42: setup shows a small choice; the rest is available, not present."""
        self._options_shown = not self._options_shown
        self._more.setText(HIDE_OPTIONS if self._options_shown else SHOW_OPTIONS)
        self._picker.setVisible(self._options_shown)
        self._fit.setVisible(self._options_shown)
        self._describe()

    def _model_changed(self) -> None:
        """Picking a different model does clear the last one's result."""
        self._status.setText("")
        self._describe()

    # -- installing ---------------------------------------------------------

    def _start(self) -> None:
        entry = self._entry()
        if entry is None:
            return
        self._cancelled = False
        self._install.setEnabled(False)
        self._picker.setEnabled(False)
        self.wizard.set_busy(True)

        if downloader.is_installed(entry):
            self._verify(entry)
            return

        self._cancel.show()
        self._bar.setValue(0)
        self._bar.show()
        self._status.setText(f"Downloading {entry.info.name}...")
        self._activity.show_working(f"Installing {entry.info.name}")

        # The entry travels on the step, not in a lambda. A lambda has no receiver
        # QObject for PySide6 to find, so the connection is DIRECT and the handler runs
        # on the worker thread -- touching a progress bar, a status label and the eagle
        # from off the GUI thread. Phase 12; see the note in ``main_window``.
        self._pending = entry
        worker = _DownloadWorker(entry, lambda: self._cancelled)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._downloaded)
        self._thread = run_in_thread(self, worker)

    def _request_cancel(self) -> None:
        self._cancelled = True
        self._status.setText("Stopping...")
        self._cancel.setEnabled(False)

    def _on_progress(self, progress: downloader.Progress) -> None:
        self._bar.setValue(progress.percent)
        self._status.setText(f"Downloading — {progress.describe()}")

    def _downloaded(self, result: downloader.DownloadResult) -> None:
        entry = self._pending
        self._activity.done()
        self._bar.hide()
        self._cancel.hide()
        self._cancel.setEnabled(True)
        if not result.ok:
            self._status.setText(result.message)
            self._finish_attempt()
            return
        self._verify(entry)

    # -- verifying ----------------------------------------------------------

    def _verify(self, entry) -> None:
        self._pending = entry
        self._status.setText(f"Checking {entry.info.name} can answer...")
        self._activity.show_working(f"Checking {entry.info.name}")
        worker = _VerifyWorker(entry)
        worker.finished.connect(self._verified)
        self._thread = run_in_thread(self, worker)

    def _verified(self, result: downloader.VerificationResult) -> None:
        entry = self._pending
        if result.ok:
            # Only now. Section 35A: "The wizard should only mark the model as ready
            # after this test succeeds" -- a finished download is not a working model.
            self.state.preferred_model = entry.info.id
            if entry.info.id not in self.state.installed_models:
                self.state.installed_models.append(entry.info.id)
            self._status.setText("\n".join(result.lines()))
            # It is on disk now, so the page should stop offering to download it. The
            # verdict is recomputed rather than patched, because "installed" also
            # changes whether free disk is checked at all.
            if self._machine is not None:
                self._verdicts[entry.info.id] = compatibility.assess(
                    entry, self._machine, installed=True
                )
        else:
            self._status.setText(result.message or "That model could not be checked.")
        self._finish_attempt()

    def _finish_attempt(self) -> None:
        self._activity.done()
        self._install.setEnabled(True)
        self._picker.setEnabled(True)
        self.wizard.set_busy(False)
        self._describe()

    def leave(self) -> bool:
        if self.state.preferred_model:
            return True
        return self.wizard.confirm(
            "Continue without a local AI?",
            "Open Nest will need cloud AI to help with anything, which uses the "
            "internet and costs money.\n\nYou can add a local model later in Settings.",
        )


class ArduinoStep(Step):
    """Decision D7. Not in section 35A's list of steps, and needed anyway.

    Phase 7 shipped a working Arduino compile whose toolchain only a developer command
    could install, so the profile could make a project and never build one. This is the
    parent-facing way to get it, kept as a choice rather than folded into the default
    install because it is another 341 MB.
    """

    title = "Arduino projects (optional)"

    def build(self) -> None:
        self.body.addWidget(_body(
            "To build Arduino projects, Open Nest needs Arduino's own tools. They are "
            f"about {toolchain.APPROXIMATE_MB} MB and are only used for Arduino "
            "projects.\n\n"
            "Everything else — games, research, pictures, Raspberry Pi — works without "
            "them, and you can add them later in Settings."
        ))
        self.body.addWidget(horizontal_rule())
        self._status = _mono("")
        self.body.addWidget(self._status)
        self._activity = _Activity(theme.is_dark())
        self.body.addWidget(self._activity)

        row = QHBoxLayout()
        self._install = QPushButton("Install Arduino Tools")
        self._install.clicked.connect(self._start)
        row.addWidget(self._install)
        row.addStretch(1)
        self.body.addLayout(row)

        self.body.addWidget(_body(
            "Only boards in the Arduino AVR family — Uno, Nano, Mega and similar — are "
            "supported today. A board outside that family will not appear in the list."
        ))
        self.body.addStretch(1)
        self._thread = None

    def enter(self) -> None:
        if toolchain.is_installed():
            self._status.setText("✓ The Arduino tools are installed.")
            self._install.setEnabled(False)
            self.state.arduino_installed = True
        else:
            self._status.setText("○ Not installed.")
            self._install.setEnabled(True)

    def _start(self) -> None:
        self._install.setEnabled(False)
        self.wizard.set_busy(True)
        self._status.setText("Starting...")
        self._activity.show_working("Installing the Arduino tools")
        worker = _ToolchainWorker()
        worker.progress.connect(self._status.setText)
        worker.finished.connect(self._done)
        self._thread = run_in_thread(self, worker)

    def _done(self, result: toolchain.ToolchainResult) -> None:
        self._activity.done()
        self._status.setText(result.message)
        self.state.arduino_installed = bool(result.ok)
        self._install.setEnabled(not result.ok)
        self.wizard.set_busy(False)


class CloudStep(Step):
    """Section 35A step 4 and "Cloud feature master switch"."""

    title = "Cloud AI (optional)"

    def build(self) -> None:
        self.body.addWidget(_body(
            "Open Nest can also use AI services on the internet. This is optional and "
            "you can skip it completely.\n\n"
            "If you turn it on, what a child types may be sent to that company, and it "
            "may cost money."
        ))
        explain = QPushButton("What is an API key?")
        explain.clicked.connect(lambda: consent.explain_api_keys(self))
        row = QHBoxLayout()
        row.addWidget(explain)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(horizontal_rule())

        self._rows: dict = {}
        for provider in keychain.CLOUD_PROVIDERS:
            self.body.addWidget(self._provider_row(provider))
            self.body.addWidget(horizontal_rule())

        self.body.addWidget(section_label("Allow Cloud AI"))
        self._switch = QComboBox()
        self._switch.addItem("Off", False)
        self._switch.addItem("On", True)
        self.body.addWidget(self._switch)
        self.body.addWidget(_body(
            "Off means no cloud request is made at all, even with a key saved. You can "
            "change this later without deleting the key."
        ))
        self.body.addStretch(1)

    def _provider_row(self, provider: str) -> QWidget:
        label = keychain.PROVIDER_LABELS.get(provider, provider)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(section_label(label))

        entry = QLineEdit()
        entry.setEchoMode(QLineEdit.EchoMode.Password)
        entry.setPlaceholderText(f"Paste the {label} API key")
        layout.addWidget(entry)

        status = _mono("Not configured")
        buttons = QHBoxLayout()
        save = QPushButton("Save Key")
        save.clicked.connect(lambda: self._save(provider, entry, status))
        test = QPushButton("Test Connection")
        test.clicked.connect(lambda: self._test(provider, status))
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: self._remove(provider, status))
        buttons.addWidget(save)
        buttons.addWidget(test)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        buttons.addWidget(status)
        layout.addLayout(buttons)

        self._rows[provider] = (entry, status)
        return widget

    def enter(self) -> None:
        self._switch.setCurrentIndex(1 if self.wizard.controls.allow_cloud_ai else 0)
        self._refresh()

    def _refresh(self) -> None:
        for status in self.wizard.credentials.statuses():
            row = self._rows.get(status.provider)
            if row is not None:
                row[1].setText(status.summary)

    def _save(self, provider: str, entry: QLineEdit, status: QLabel) -> None:
        key = entry.text().strip()
        if not key:
            return
        try:
            self.wizard.credentials.save_key(provider, key)
        except keychain.CredentialError as exc:
            self.wizard.complain(str(exc))
            return
        # Straight to the Keychain and out of the widget. Section 35A lists installer
        # logs, project files and plaintext settings as places it must never go, and
        # the shortest way to satisfy that is for nothing to hold it.
        entry.clear()
        self._refresh()

    def _remove(self, provider: str, status: QLabel) -> None:
        try:
            self.wizard.credentials.delete_key(provider)
        except keychain.CredentialError as exc:
            self.wizard.complain(str(exc))
            return
        self._refresh()

    def _test(self, provider: str, status: QLabel) -> None:
        """Section 35A's "Test Connection". The only outbound request setup makes."""
        entry = next(
            (e for e in router.cloud_models() if e.info.provider == provider), None
        )
        if entry is None:
            self.wizard.complain(f"No {provider} model is configured.")
            return
        try:
            built = router.build_provider(
                entry.info.id, allow_cloud=True, credentials=self.wizard.credentials
            )
            message = built.check_connection()
        except ProviderError as exc:
            self.wizard.complain(str(exc))
            return
        QMessageBox.information(self, APP_NAME, message)

    def leave(self) -> bool:
        wanted = bool(self._switch.currentData())
        if wanted and not any(s.configured for s in self.wizard.credentials.statuses()):
            return self.wizard.confirm(
                "Turn cloud AI on with no key saved?",
                "Nothing will work until a key is added. You can add one later in "
                "Settings.",
            )
        self.wizard.controls.allow_cloud_ai = wanted
        self.state.cloud_enabled = wanted
        return True


class GitStep(Step):
    """Section 35A step 5: version history, the GitHub connection, and PR behaviour.

    GitHub is optional and says so -- section 35A: "GitHub must not be mandatory."
    Local version history is presented first and separately, because it is the part
    that always works: no account, no internet, nothing to decide.

    The four defaults offered here are section 35A's "Recommended defaults" exactly --
    private repositories on, backup on if connected, automatic PRs off, conversation
    history off.
    """

    title = "Version history"

    def build(self) -> None:
        self._git = _mono("Checking...")
        self.body.addWidget(section_label("Version history"))
        self.body.addWidget(self._git)
        self.body.addWidget(_body(
            "Open Nest automatically keeps safe versions of every project on this Mac, "
            "so a child can always undo. This works with no account and no internet."
        ))
        self.body.addWidget(horizontal_rule())

        self.body.addWidget(section_label("GitHub backup"))
        self._github_body = _body("")
        self.body.addWidget(self._github_body)
        self._github_status = _mono("")
        self.body.addWidget(self._github_status)

        github_row = QHBoxLayout()
        self._connect = QPushButton("Connect GitHub")
        self._connect.clicked.connect(self._connect_github)
        self._disconnect = QPushButton("Disconnect")
        self._disconnect.clicked.connect(self._disconnect_github)
        github_row.addWidget(self._connect)
        github_row.addWidget(self._disconnect)
        github_row.addStretch(1)
        self.body.addLayout(github_row)

        self.body.addWidget(horizontal_rule())
        self.body.addWidget(section_label("AI change review"))
        self.body.addWidget(_body("How should Open Nest handle large changes?"))
        self._pr_policy = QComboBox()
        for value in permissions.PR_POLICIES:
            self._pr_policy.addItem(permissions.PR_POLICY_LABELS[value], value)
        self.body.addWidget(self._pr_policy)
        self.body.addStretch(1)

    def enter(self) -> None:
        from opennest.github import auth as github_auth
        from opennest.versioning import git_manager

        if git_manager.git_available():
            self._git.setText("Git is installed.")
        else:
            self._git.setText(
                "Git is not installed, so Open Nest cannot save versions of a project. "
                "Installing Apple's command line tools adds it:  xcode-select --install"
            )

        if not github_auth.configured():
            # Phase 8's stance, kept: state the absence rather than showing a button
            # that cannot work. Nothing here fakes a connection.
            self._github_body.setText(
                "Backing projects up to a private GitHub repository is not part of "
                "this version of Open Nest. Nothing is sent anywhere, and version "
                "history on this Mac works without it."
            )
            self._github_status.setText("")
            self._connect.setVisible(False)
            self._disconnect.setVisible(False)
            return

        self._github_body.setText(
            "Open Nest can privately back up every project to a GitHub account, so "
            "the work survives this Mac. Repositories are always private, and this is "
            "the parent's account -- the child never signs in to anything.\n\n"
            "This is optional. Everything works without it."
        )
        self._refresh_github()

    def leave(self) -> bool:
        from opennest.github import auth as github_auth

        connected = github_auth.configured() and github_auth.connected(
            self.wizard.credentials
        )
        self.state.github_enabled = connected
        if not connected:
            self.state.github_account = ""
        # Section 35A: "Automatic backup: ON if GitHub is connected." The switch itself
        # defaults on, so this is only ever turning it off when there is no account.
        self.wizard.controls.github_private_backup = connected
        self.wizard.controls.github_pr_policy = self._pr_policy.currentData()
        return True

    # -- the connection -----------------------------------------------------

    def _connect_github(self) -> None:
        from opennest.ui.github_connect import connect_github

        login = connect_github(self, credentials=self.wizard.credentials)
        if not login:
            return
        # Recorded on the wizard's own state object, not written here: the wizard saves
        # installation.json once, at the end, so a parent who quits half way through
        # has not had a partial record written for them.
        self.state.github_enabled = True
        self.state.github_account = login
        self._refresh_github()

    def _disconnect_github(self) -> None:
        from opennest.github import auth as github_auth

        github_auth.disconnect(self.wizard.credentials)
        self.state.github_enabled = False
        self.state.github_account = ""
        self._refresh_github()

    def _refresh_github(self) -> None:
        from opennest.github import auth as github_auth

        connected = github_auth.connected(self.wizard.credentials)
        self._connect.setVisible(not connected)
        self._disconnect.setVisible(connected)
        if connected:
            account = self.state.github_account
            self._github_status.setText(
                f"Connected{f' as {account}' if account else ''}.\n"
                "New projects will be backed up to a private repository."
            )
        else:
            self._github_status.setText("Not connected.")


class ParentStep(Step):
    """Section 35A step 6. The PIN is what makes every other gate mean something."""

    title = "Parent settings"

    def build(self) -> None:
        self.body.addWidget(_body(
            "A parent PIN protects these settings. Open Nest stores only a fingerprint "
            "of it, never the PIN itself."
        ))
        self._pin = _field(self.body, "Create a parent PIN", "at least four characters")
        self._pin.setEchoMode(QLineEdit.EchoMode.Password)
        self._again = _field(self.body, "Type it again", "")
        self._again.setEchoMode(QLineEdit.EchoMode.Password)
        self._pin_note = _mono("")
        self.body.addWidget(self._pin_note)
        self.body.addWidget(_body(
            "You can leave this blank. Open Nest will then ask before anything below "
            "happens, but anyone using this Mac can answer."
        ))
        self.body.addWidget(horizontal_rule())

        self._gates: dict = {}
        for gate in permissions.GATES:
            self.body.addWidget(self._gate_row(gate))
        self.body.addStretch(1)

    def _gate_row(self, gate: permissions.Gate) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)

        caption = QLabel(gate.label)
        caption.setProperty("role", "cardTitle")
        layout.addWidget(caption)
        layout.addWidget(_body(gate.explanation))

        box = QComboBox()
        for value in permissions.STATES:
            if value == permissions.ASK and not gate.supports_ask:
                continue
            box.addItem(permissions.STATE_LABELS[value], value)
        layout.addWidget(box)
        self._gates[gate.name] = box
        return widget

    def enter(self) -> None:
        for name, box in self._gates.items():
            index = box.findData(self.wizard.controls.state(name))
            box.setCurrentIndex(max(0, index))
        if self.wizard.credentials.parent_pin_set():
            self._pin_note.setText("A PIN is already set. Leave these blank to keep it.")
        else:
            self._pin_note.setText("No PIN is set yet.")

    def initial_focus(self) -> QWidget | None:
        return self._pin

    def leave(self) -> bool:
        pin = self._pin.text()
        again = self._again.text()
        if pin or again:
            if pin != again:
                self.wizard.complain("Those PINs did not match. Nothing was saved.")
                return False
            try:
                self.wizard.credentials.set_parent_pin(pin)
            except keychain.CredentialError as exc:
                self.wizard.complain(str(exc))
                return False
            self._pin.clear()
            self._again.clear()

        for name, box in self._gates.items():
            self.wizard.controls.set_state(name, box.currentData())
        try:
            self.wizard.controls.save()
        except (OSError, ValueError) as exc:
            self.wizard.complain(str(exc))
            return False
        permissions.reload()
        return True


class HealthStep(Step):
    """Section 35A step 7, the installation test."""

    title = "Checking everything works"

    def build(self) -> None:
        self._summary = _body("")
        self.body.addWidget(self._summary)
        self._results = _mono("")
        self.body.addWidget(self._results)
        again = QPushButton("Check Again")
        again.clicked.connect(self.enter)
        row = QHBoxLayout()
        row.addWidget(again)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addStretch(1)
        self._blocking: tuple = ()

    def enter(self) -> None:
        results = checks.run(
            self.wizard.controls,
            self.wizard.credentials,
            preferred_model=self.state.preferred_model,
        )
        self._results.setText(checks.report(results))
        self._summary.setText(checks.summary(results))
        self._blocking = checks.blocking(results)

    def leave(self) -> bool:
        if not self._blocking:
            return True
        names = ", ".join(check.name.lower() for check in self._blocking)
        return self.wizard.confirm(
            "Finish anyway?",
            f"These are not working: {names}.\n\nOpen Nest will open, but some of it "
            f"will not work until they are fixed.",
        )


class FinishStep(Step):
    """Section 35A step 8, and guide section 58's closing moment.

    The third of the three graphics that teach the visual language: identity at the
    start, the eagle while something installs, the approval mark when it is done. This
    is also the clearest case in the whole product for the sunglasses -- section 38's
    first example is literally a finished setup -- and it is rare by construction,
    because a parent sees it once.
    """

    # Not "Open Nest is ready" any more: guide section 58 puts that sentence next to the
    # approval mark below, and the rendered page said it twice, once as chrome and once
    # as the moment. The heading gives way, because the graphic and its line are the
    # part that is supposed to land.
    title = "Setup complete"
    next_label = "Launch Open Nest"

    def build(self) -> None:
        approval = QHBoxLayout()
        approval.setSpacing(12)
        approval.addWidget(
            brand.placed("completion_glasses", dark=theme.is_dark()),
            0, Qt.AlignmentFlag.AlignVCenter,
        )
        ready = QLabel(f"{APP_NAME} is ready.")
        ready.setProperty("role", "greeting")
        approval.addWidget(ready, 1, Qt.AlignmentFlag.AlignVCenter)
        self.body.addLayout(approval)
        self.body.addSpacing(6)

        self._summary = _mono("")
        self.body.addWidget(self._summary)
        self.body.addStretch(1)

    def enter(self) -> None:
        model = "Not installed"
        if self.state.preferred_model:
            try:
                model = router.get_entry(self.state.preferred_model).info.name
            except Exception:
                model = self.state.preferred_model
        cloud = "On" if self.state.cloud_enabled else "Not enabled"
        pin = "Set" if self.wizard.credentials.parent_pin_set() else "Not set"
        self._summary.setText(
            f"For              {self.state.child_name or 'this Mac'}\n"
            f"Local AI         {model}\n"
            f"Cloud AI         {cloud}\n"
            f"Parent PIN       {pin}\n"
            f"Projects         {paths.projects_root()}"
        )


#: Section 35A's order, with the Arduino step inserted after Local AI -- both are
#: "what do you want installed on this Mac", and both are large downloads worth
#: deciding about before the questions that only take a moment.
STEPS: tuple = (
    WelcomeStep, IdentityStep, LocalAIStep, ArduinoStep, CloudStep,
    GitStep, ParentStep, HealthStep, FinishStep,
)


# --------------------------------------------------------------------------- workers

def inspect_machine(machine=None):
    """Read the Mac, find what is already installed, and judge one against the other.

    No Qt, so it runs on a worker thread or inline. ``machine`` overrides detection,
    which is what lets the recommendation be tested for Macs nobody here owns.

    Deliberately does not refresh the remote catalogue -- section 45 forbids blocking on
    the network, and a parent who wants a newer list presses the button in Settings.
    """
    profile = machine if machine is not None else machine_service.detect()
    entries = router.local_models()
    try:
        installed = discovery.installed(router.load_catalogue())
    except Exception:
        # A cache Open Nest cannot read is not a reason to fail setup. The worst case is
        # offering to download something already present, which wastes bandwidth rather
        # than breaking anything.
        installed = ()
    installed_ids = [item.model_id for item in installed]
    verdicts = {
        verdict.model_id: verdict
        for verdict in compatibility.assess_all(entries, profile, installed_ids)
    }
    return profile, verdicts, installed


class _InspectWorker(QObject):
    """:func:`inspect_machine`, off the UI thread.

    Both halves are genuinely slow enough to matter: the hardware means subprocesses,
    and finding an existing model means asking huggingface_hub about every catalogue
    entry across every approved cache. Neither belongs on the thread drawing the window,
    and together they are what entitles this page to the eagle.
    """

    finished = Signal(object)

    def run(self) -> None:
        self.finished.emit(inspect_machine())


class _DownloadWorker(QObject):
    """One model download, off the UI thread so Cancel can be pressed."""

    progress = Signal(object)
    finished = Signal(object)

    def __init__(self, entry, should_cancel) -> None:
        super().__init__()
        self.entry = entry
        self.should_cancel = should_cancel

    def run(self) -> None:
        result = downloader.download(
            self.entry,
            on_progress=self.progress.emit,
            should_cancel=self.should_cancel,
        )
        self.finished.emit(result)


class _VerifyWorker(QObject):
    """One real inference, off the UI thread because loading a 4B model takes seconds."""

    finished = Signal(object)

    def __init__(self, entry) -> None:
        super().__init__()
        self.entry = entry

    def run(self) -> None:
        self.finished.emit(downloader.verify(self.entry))


class _ToolchainWorker(QObject):
    """The Arduino install: two downloads and a 324 MB core, so minutes, not seconds."""

    progress = Signal(str)
    finished = Signal(object)

    def run(self) -> None:
        self.finished.emit(toolchain.install(on_progress=self.progress.emit))


# --------------------------------------------------------------------------- the wizard

class SetupWizard(QDialog):
    """The eight steps, and the installation record they build up."""

    def __init__(
        self,
        parent=None,
        *,
        state: InstallationState | None = None,
        controls: permissions.ParentControls | None = None,
        credentials: keychain.Credentials | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Setup")
        self.resize(640, 620)
        self.state = state if state is not None else InstallationState.load()
        self.controls = controls if controls is not None else permissions.current()
        self.credentials = credentials or keychain.default()
        #: Set while a download or a verification is running, so Back and Continue do
        #: not navigate out from under a worker thread.
        self._busy = False
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        self._heading = QLabel("")
        self._heading.setProperty("role", "greeting")
        outer.addWidget(self._heading)
        self._progress = QLabel("")
        self._progress.setProperty("role", "mono")
        outer.addWidget(self._progress)
        outer.addWidget(horizontal_rule())

        self._stack = QStackedWidget()
        self.steps = [factory(self) for factory in STEPS]
        for step in self.steps:
            outer_widget = QWidget()
            wrapper = QVBoxLayout(outer_widget)
            wrapper.setContentsMargins(0, 0, 0, 0)
            wrapper.addWidget(step)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(outer_widget)
            self._stack.addWidget(area)
        outer.addWidget(self._stack, 1)

        outer.addWidget(horizontal_rule())
        footer = QHBoxLayout()
        self._back = QPushButton("Back")
        self._back.clicked.connect(self._go_back)
        self._next = QPushButton("Continue")
        self._next.setProperty("role", "primary")
        self._next.clicked.connect(self._go_next)
        quit_button = QPushButton("Quit Setup")
        quit_button.clicked.connect(self.reject)
        footer.addWidget(quit_button)
        footer.addStretch(1)
        footer.addWidget(self._back)
        footer.addWidget(self._next)
        outer.addLayout(footer)

        # Return has to mean Continue, and until Phase 12 it meant nothing. QPushButton
        # sets ``autoDefault`` inside a QDialog, so Qt picked a default on its own: it
        # chose "Show other options" -- a control on the Local AI step, invisible from
        # every other page. So a parent who typed a name and pressed Return got no
        # response at all, and on one page would have toggled a fold-out they were not
        # looking at. Every button gives up autoDefault; the primary action claims it.
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self._next.setAutoDefault(True)
        self._next.setDefault(True)

        self._show_step(0)

    # -- navigation ---------------------------------------------------------

    @property
    def index(self) -> int:
        return self._stack.currentIndex()

    def _show_step(self, index: int) -> None:
        index = max(0, min(index, len(self.steps) - 1))
        self._stack.setCurrentIndex(index)
        step = self.steps[index]
        self._heading.setText(step.title)
        self._progress.setText(f"STEP {index + 1} OF {len(self.steps)}")
        self._next.setText(step.next_label)
        self._back.setEnabled(index > 0)
        step.enter()
        # After ``enter``, because a step may only know what to focus once it has
        # refreshed. Arriving at "Who will use Open Nest?" used to leave focus on the
        # page's QScrollArea, so the one field a parent has to fill in was not where
        # their typing went.
        target = step.initial_focus()
        if target is not None:
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _go_back(self) -> None:
        if self._busy:
            return
        self._show_step(self.index - 1)

    def _go_next(self) -> None:
        if self._busy:
            return
        step = self.steps[self.index]
        if not step.leave():
            return
        if self.index >= len(self.steps) - 1:
            self._finish()
            return
        self._show_step(self.index + 1)

    def set_busy(self, busy: bool) -> None:
        """Stop navigation while a worker thread owns the current step."""
        self._busy = busy
        self._next.setEnabled(not busy)
        self._back.setEnabled(not busy and self.index > 0)

    # -- asking -------------------------------------------------------------

    # -- shutting down ------------------------------------------------------

    def wait_for_workers(self) -> None:
        """Let every step's worker finish before this dialog goes away.

        A model download, a verification, a toolchain install and the machine inspection
        all run on threads parented to a step. Destroying the wizard underneath one of
        them aborts the interpreter outright -- see ``ui.worker.stop_thread``. Quit Setup
        is the route that reaches it, because ``set_busy`` disables Back and Continue and
        deliberately does not disable quitting.
        """
        for step in self.steps:
            stop_thread(getattr(step, "_thread", None))

    def done(self, result: int) -> None:
        """Both Accept and Reject funnel through here, so this is the one place to wait."""
        self.wait_for_workers()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.wait_for_workers()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """Escape does not end setup.

        A QDialog rejects on Escape, and rejecting here is what "Quit Setup" does:
        ``installation.json`` is written once, at the end, so everything held on
        ``self.state`` -- the child's name, the Git identity, which model was verified,
        whether cloud was enabled, the GitHub account -- is discarded, ``setup_complete``
        stays false, and the next launch starts the wizard again from step 1. No
        confirmation, no warning, one key.

        Quit Setup is still there and still immediate: that is a button somebody chose
        to press. This is the accident, and nothing else in this file has a destructive
        step reachable by mistake.
        """
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def complain(self, message: str) -> None:
        QMessageBox.warning(self, f"{APP_NAME} Setup", message)

    def confirm(self, question: str, detail: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(f"{APP_NAME} Setup")
        box.setText(question)
        box.setInformativeText(detail)
        proceed = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Go Back", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        return box.clickedButton() is proceed

    # -- finishing ----------------------------------------------------------

    def _finish(self) -> None:
        """Record the installation, then let the caller launch the app."""
        self.state.setup_complete = True
        # Adopt this checkout as the one we are known to work against, so the next
        # launch after a `git pull` can tell what moved (DoD 51-53).
        self.state.record_launch()
        try:
            self.state.save()
        except (OSError, ValueError) as exc:
            self.complain(f"Open Nest could not record the setup.\n\n{exc}")
            return
        self.accept()


def run_wizard(argv=None) -> int:
    """Entry point. Started by the bootstrap when setup has not been completed."""
    paths.ensure_app_dirs()
    app = QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    theme.apply(app)

    wizard = SetupWizard()
    if wizard.exec() != QDialog.DialogCode.Accepted:
        return 1

    # Section 35A step 8's "[ Launch Build Lab ]". Replacing this process rather than
    # spawning one keeps a single window in the Dock.
    from opennest.app import main as run_app

    return run_app([sys.argv[0]] if argv is None else list(argv)[:1])


if __name__ == "__main__":
    sys.exit(run_wizard())
