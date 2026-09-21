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

from PySide6.QtCore import QObject, Signal
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
from opennest.security import keychain, permissions
from opennest.setup import checks, downloader, toolchain
from opennest.setup.state import InstallationState
from opennest.ui import consent, theme
from opennest.ui.common import horizontal_rule, section_label
from opennest.ui.worker import run_in_thread


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


class WelcomeStep(Step):
    """Section 35A step 1, plus the "Installation environment" hardware summary."""

    title = "Welcome to Open Nest"
    next_label = "Get Started"

    def build(self) -> None:
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
        machine = _detect_machine()
        if machine is None:
            self._machine.setText("This Mac could not be inspected.")
            return
        hardware = "Apple silicon" if machine.is_apple_silicon else machine.arch
        self._machine.setText(
            f"Mac              {hardware}\n"
            f"macOS            {machine.macos_version or 'unknown'}\n"
            f"Memory           {machine.memory_gb:.0f} GB\n"
            f"Free storage     {machine.free_disk_gb:.0f} GB"
        )
        problems = machine.problems()
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
    """Sections 35A steps 3, "Model installation" and "Model verification"."""

    title = "Local AI"

    def build(self) -> None:
        self.body.addWidget(_body(
            "Open Nest uses an AI model that runs on this Mac. Nothing a child types "
            "goes to the internet while they use it."
        ))
        self._picker = QComboBox()
        self.body.addWidget(self._picker)
        self._detail = _mono("")
        self.body.addWidget(self._detail)

        self.body.addWidget(horizontal_rule())
        self._status = _body("")
        self.body.addWidget(self._status)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.hide()
        self.body.addWidget(self._bar)

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

    def enter(self) -> None:
        if self._picker.count():
            self._describe()
            return
        # Straight from the catalogue: section 35A forbids hard-coding model ids or
        # sizes into wizard logic, and recommended-ness is a field on the entry.
        for entry in router.local_models():
            mark = "Recommended — " if entry.recommended else ""
            self._picker.addItem(f"{mark}{entry.info.name}", entry.info.id)
        preferred = self.state.preferred_model or router.default_model_id()
        index = self._picker.findData(preferred)
        self._picker.setCurrentIndex(max(0, index))
        self._describe()

    # -- the chosen model ---------------------------------------------------

    def _entry(self):
        model_id = self._picker.currentData()
        return router.get_entry(model_id) if model_id else None

    def _describe(self) -> None:
        """Refresh the size line and the button, and deliberately not the status.

        ``_finish_attempt`` calls this, and an earlier version cleared the status here
        too -- which wiped "could not be downloaded" in the same instant it appeared.
        A failure a parent cannot read is a failure they will hit again.
        """
        entry = self._entry()
        if entry is None:
            return
        if downloader.is_installed(entry):
            self._detail.setText(f"Already on this Mac. About {entry.download_gb} GB.")
            self._install.setText("Check It Works")
        else:
            self._detail.setText(f"Download is about {entry.download_gb} GB.")
            self._install.setText("Install")

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

        worker = _DownloadWorker(entry, lambda: self._cancelled)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(lambda result: self._downloaded(entry, result))
        self._thread = run_in_thread(self, worker)

    def _request_cancel(self) -> None:
        self._cancelled = True
        self._status.setText("Stopping...")
        self._cancel.setEnabled(False)

    def _on_progress(self, progress: downloader.Progress) -> None:
        self._bar.setValue(progress.percent)
        self._status.setText(f"Downloading — {progress.describe()}")

    def _downloaded(self, entry, result: downloader.DownloadResult) -> None:
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
        self._status.setText(f"Checking {entry.info.name} can answer...")
        worker = _VerifyWorker(entry)
        worker.finished.connect(lambda result: self._verified(entry, result))
        self._thread = run_in_thread(self, worker)

    def _verified(self, entry, result: downloader.VerificationResult) -> None:
        if result.ok:
            # Only now. Section 35A: "The wizard should only mark the model as ready
            # after this test succeeds" -- a finished download is not a working model.
            self.state.preferred_model = entry.info.id
            if entry.info.id not in self.state.installed_models:
                self.state.installed_models.append(entry.info.id)
            self._status.setText("\n".join(result.lines()))
        else:
            self._status.setText(result.message or "That model could not be checked.")
        self._finish_attempt()

    def _finish_attempt(self) -> None:
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
        worker = _ToolchainWorker()
        worker.progress.connect(self._status.setText)
        worker.finished.connect(self._done)
        self._thread = run_in_thread(self, worker)

    def _done(self, result: toolchain.ToolchainResult) -> None:
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
    """Section 35A step 5. GitHub itself is Phase 9 (decision D1), and says so."""

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
        self.body.addWidget(_body(
            "Backing projects up to a private GitHub repository is not available in "
            "this version yet. Nothing is sent anywhere, and local version history "
            "works without it."
        ))
        self.body.addWidget(horizontal_rule())

        self.body.addWidget(section_label("AI change review"))
        self.body.addWidget(_body("How should Open Nest handle large changes?"))
        self._pr_policy = QComboBox()
        self._pr_policy.addItem("Save them normally", "normal")
        self._pr_policy.addItem("Create a review branch", "branch")
        self.body.addWidget(self._pr_policy)
        self.body.addStretch(1)

    def enter(self) -> None:
        from opennest.versioning import git_manager

        if git_manager.git_available():
            self._git.setText("Git is installed.")
        else:
            self._git.setText(
                "Git is not installed, so Open Nest cannot save versions of a project. "
                "Installing Apple's command line tools adds it:  xcode-select --install"
            )

    def leave(self) -> bool:
        self.state.github_enabled = False
        return True


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
    """Section 35A step 8."""

    title = "Open Nest is ready"
    next_label = "Launch Open Nest"

    def build(self) -> None:
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


def _detect_machine():
    """The hardware panel, from the bootstrap's own detection.

    Imported lazily and tolerantly: the bootstrap is the authority on what this Mac is,
    but the wizard should still open if it cannot be reached. The dependency only goes
    this way -- the bootstrap must never import the application.
    """
    try:
        from bootstrap import environment

        return environment.detect_machine()
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(run_wizard())
