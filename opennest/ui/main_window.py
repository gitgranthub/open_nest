"""The Open Nest main window: Flight Deck and Workbench in one shell."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from opennest import APP_NAME
from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai import images
from opennest.ai.provider import ProviderError
from opennest.ai.router import build_provider, default_model_id, get_entry, unmet_requirements
from opennest.memory.manager import MemoryManager
from opennest.projects.manager import Project, ProjectError, create_project
from opennest.projects.profiles import Profile
from opennest.security import keychain, permissions
from opennest.setup.state import InstallationState
from opennest.ui import consent, new_project
from opennest.ui import settings as settings_ui
from opennest.ui.flight_deck import FlightDeck
from opennest.ui.github_sync import GitHubSync
from opennest.ui.workbench import Workbench
from opennest.ui.worker import ModelLoader, run_in_thread, stop_thread
from opennest.versioning.checkpoint import VersionHistory


class MainWindow(QMainWindow):
    def __init__(
        self,
        user_name: str | None = None,
        *,
        credentials=None,
        installation: InstallationState | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        # A normal desktop window: opens at a comfortable size, resizes freely, and goes
        # full screen like anything else on the Mac. The floor is the part that was
        # missing -- with no minimum the shell reported 88x88, so the window could be
        # dragged down to a size where the Workbench header clips and the three panels
        # collapse into slivers. Measured, that header needs 779 px and the whole
        # Workbench 811x444; 900x600 clears both with room and is a conventional
        # minimum. Nothing here caps the maximum, which is what lets macOS offer the
        # green full-screen button.
        self.setMinimumSize(900, 600)

        #: What the setup wizard recorded: who this is for, and what name goes on a
        #: saved version. Until Phase 8 nothing supplied either, so the greeting was
        #: anonymous and every commit was "Open Nest <opennest@localhost>".
        self.installation = (
            installation if installation is not None else InstallationState.load()
        )
        user_name = user_name or self.installation.child_name or None

        #: The parent's switches, read once and re-read whenever Settings saves.
        self.controls = permissions.current()
        #: Asked only whether a key exists. Injectable for the same reason the provider
        #: is: a test must not depend on what the developer has in their own Keychain.
        self.credentials = credentials or keychain.default()

        self._provider = None
        self._loader_thread = None
        self._workbench: Workbench | None = None
        self._versions: VersionHistory | None = None
        self._controller: AgentController | None = None

        #: GitHub backup (WORKORDER_01 section 29A). Owns the push queue and sweeps it
        #: on a timer. Constructed whether or not GitHub is connected: it checks
        #: readiness on every sweep, so a parent connecting mid-session just works, and
        #: a queue left over from a previous run is picked up on launch.
        self._sync = GitHubSync(
            self,
            credentials=self.credentials,
            controls=self.controls,
            on_problem=self._backup_problem,
            on_status=self._backup_status,
        )

        self._stack = QStackedWidget()
        self._deck = FlightDeck(
            user_name,
            allow_cloud=self.controls.cloud_allowed(),
            credentials=self.credentials,
        )
        self._deck.new_project_requested.connect(self._new_project)
        self._deck.project_opened.connect(self._open_project)
        self._deck.settings_requested.connect(self._open_settings)
        self._stack.addWidget(self._deck)
        self.setCentralWidget(self._stack)

        # After the deck exists, because the first status arrives synchronously.
        self._sync.start()
        self._show_cloud_status()
        self._start_model_load()

    # -- model --------------------------------------------------------------

    def _start_model_load(self) -> None:
        """Warm the local model in the background so the first message is not slow."""
        try:
            self._provider = build_provider(default_model_id())
        except ProviderError as exc:
            self._deck.set_model_status("attention", "Not available")
            self._model_problem = str(exc)
            return

        self._model_problem = None
        self._deck.set_model_status("working", "Starting")
        loader = ModelLoader(self._provider)
        # A bound method of a QObject, never a lambda. PySide6 works out the connection
        # type from the *receiver*: a bound method of a QObject living on the GUI thread
        # gets a queued connection across threads, while a plain lambda has no receiver
        # to find and is therefore delivered DIRECTLY -- on the worker thread. That ran
        # ``_model_ready`` off the GUI thread, which swapped a status row and stopped
        # the eagle's timer from there ("Cannot set parent, new parent is in a different
        # thread", "Timers cannot be stopped from another thread"). Invisible until
        # Phase 12 fixed ``run_in_thread``, because the worker never ran.
        loader.ready.connect(self._model_ready)
        loader.failed.connect(self._model_failed)
        self._loader_thread = run_in_thread(self, loader)

    def _model_ready(self) -> None:
        self._deck.set_model_status("ready", "Ready on this Mac")
        if self._workbench is not None:
            self._workbench.set_model_status("ready", "Ready")

    def _model_failed(self, message: str) -> None:
        self._model_problem = message
        self._deck.set_model_status("attention", "Not available")
        if self._workbench is not None:
            self._workbench.set_model_status("attention", "Not available")

    def _switch_model(self, model_id: str) -> None:
        """Change the model for the open project (WORKORDER_01 section 4, DoD 36).

        Section 38 forbids switching between local and cloud silently, and section 24
        adds the warning a cloud model needs first. So the order here is: is it allowed
        at all, then does the child have permission to use it *now*, then switch. Any
        refusal puts the picker back where it was, so what is on screen always matches
        which model is actually answering.
        """
        if self._workbench is None or self._controller is None:
            return
        current = getattr(getattr(self._controller.provider, "info", None), "id", None)
        if model_id == current:
            return

        try:
            entry = get_entry(model_id)
        except ProviderError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            self._workbench.select_model(current)
            return

        if entry.info.requires_internet:
            if not self.controls.cloud_allowed():
                QMessageBox.information(self, APP_NAME, (
                    f"{entry.info.name} uses the internet, and cloud AI is turned off.\n\n"
                    f"A parent can turn it on in Settings."
                ))
                self._workbench.select_model(current)
                return
            if self.controls.cloud_needs_confirmation() and not consent.confirm_cloud_use(
                self, entry.info
            ):
                self._workbench.select_model(current)
                return

        try:
            provider = build_provider(
                model_id,
                allow_cloud=self.controls.cloud_allowed(),
                credentials=self.credentials,
            )
            provider.load()
        except ProviderError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            self._workbench.select_model(current)
            return

        # Release the previous model's memory before the new one is in use. On an 8 GB
        # Mac this is the difference between one model resident and two.
        previous = self._controller.provider
        self._controller.use_provider(provider)
        self._provider = provider
        if previous is not None and previous is not provider:
            previous.unload()

        self._workbench.select_model(model_id)
        self._workbench.set_model_status("ready", "Ready")
        self._workbench.refresh_files()

    # -- settings -----------------------------------------------------------

    def _open_settings(self) -> None:
        window = settings_ui.open_settings(self, credentials=self.credentials)
        window.deleteLater()
        self._settings_changed()

    def _settings_changed(self) -> None:
        self.controls = permissions.reload()
        # ``reload()`` returns a new object, so anything holding the old one is now
        # reading stale switches. The sync is the case that matters: a parent turning
        # backup off would otherwise keep pushing until the next launch.
        self._sync.controls = self.controls
        self._sync.start()
        self._show_cloud_status()
        # A parent turning cloud on has to make Image Creation usable without a restart.
        self._deck.allow_cloud = self.controls.cloud_allowed()
        self._deck.refresh_profiles()
        if self._workbench is not None:
            self._workbench.allow_cloud = self.controls.cloud_allowed()
            self._workbench.refresh_models()

    def _show_cloud_status(self) -> None:
        """DESIGN_DOC section 14's ``CLOUD  OFF``. Off is a normal state, not a fault."""
        if self.controls.cloud_allowed():
            self._deck.set_cloud_status("ready", "On")
        else:
            self._deck.set_cloud_status("idle", "Off")

    # -- projects -----------------------------------------------------------

    def _new_project(self, profile: Profile) -> None:
        chosen = new_project.ask(self, profile)
        if chosen is None:
            return
        try:
            # The dialog always decides, so PROFILE_DEFAULT never reaches here: by this
            # point "empty" is a choice the child made rather than one nobody made.
            project = create_project(
                chosen.name, profile.id,
                model=default_model_id(),
                starter_id=chosen.starter_id,
            )
        except ProjectError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._deck.refresh()
        # WORKORDER_01 section 27's idea cards are section 5's "suggested starter
        # prompts": the chosen one is filled into the message box, not sent, so they can
        # add to it first.
        self._open_project(project, starter_idea=chosen.starter_idea)

    def _open_project(self, project: Project, *, starter_idea: str | None = None) -> None:
        if self._provider is None:
            QMessageBox.warning(
                self, APP_NAME,
                self._model_problem or "The local AI is not available yet.",
            )
            return

        # Say up front when the chosen model cannot do this kind of project, rather
        # than letting the child discover it by watching nothing happen.
        unmet = unmet_requirements(self._provider.info, project.profile)
        if unmet:
            QMessageBox.warning(self, APP_NAME, "\n\n".join(unmet))
            return

        # And when the profile itself needs something that is not configured. Checked
        # here as well as on the card, because an existing project can be reopened from
        # Recent Projects after a parent turns cloud back off.
        blocked = images.unmet_requirements(
            project.profile,
            allow_cloud=self.controls.cloud_allowed(),
            credentials=self.credentials,
        )
        if blocked:
            QMessageBox.warning(self, APP_NAME, blocked)
            return

        versions = VersionHistory(project)
        # Section 35A step 2's Git identity, finally reaching the thing it names.
        # Blank falls through to git_manager's defaults, which is the right behaviour
        # when a parent skipped the field: a saved version is still made.
        versions.start(
            author_name=self.installation.git_author_name or None,
            author_email=self.installation.git_author_email or None,
        )
        recovery = versions.recover()

        controller = AgentController(
            project,
            self._provider,
            Toolbox(project, network_policy=self._network_allowed),
            build_style=project.manifest.build_style,
            versions=versions,
            memory=MemoryManager.for_provider(project, self._provider, versions=versions),
        )
        workbench = Workbench(
            project, controller, versions,
            allow_cloud=self.controls.cloud_allowed(),
            credentials=self.credentials,
            upload_policy=self._upload_allowed,
            starter_idea=starter_idea,
            sync=self._sync,
        )
        workbench.back_requested.connect(self._back_to_deck)
        workbench.model_change_requested.connect(self._switch_model)

        if self._workbench is not None:
            self._stack.removeWidget(self._workbench)
            self._workbench.deleteLater()
        self._workbench = workbench
        self._versions = versions
        self._controller = controller
        self._stack.addWidget(workbench)
        self._stack.setCurrentWidget(workbench)
        if self._provider.is_loaded:
            workbench.set_model_status("ready", "Ready")
        # Only mentioned when something actually happened (WORKORDER_01 section 29A).
        if recovery.recovered:
            QMessageBox.information(self, APP_NAME, recovery.message)

    def _network_allowed(self) -> bool:
        """Whether a project run may reach the internet (WORKORDER_01 section 25).

        Consulted at the moment of the run rather than when the project opened, so a
        parent changing the setting takes effect on the next run and not the next
        launch. "Ask Parent" becomes a dialog here, which is why the toolbox takes a
        callable rather than a flag.
        """
        return self.controls.network_for_runs(
            lambda gate: consent.approve(self, gate)
        )

    def _upload_allowed(self) -> bool:
        """Whether a sketch may be sent to a board (WORKORDER_01 section 25).

        The gate has existed since Phase 6 with nothing consuming it; this is its first
        consumer. Same shape as ``_network_allowed`` deliberately -- one permission
        mechanism, asked at the moment the action is taken.
        """
        return self.controls.gate(
            "arduino_upload", lambda gate: consent.approve(self, gate)
        )

    def _back_to_deck(self) -> None:
        self._close_project()
        self._deck.refresh()
        self._stack.setCurrentWidget(self._deck)

    def _backup_status(self, status) -> None:
        """Follow the backup state on the Flight Deck's status footer.

        Only the child-facing half is shown here. The queue depth, why a push is
        waiting and anything that failed are the parent's, and live in Settings --
        section 29A's rule is that a child's normal experience gains no complexity from
        backup existing, not that they must be unaware their work is safe.
        """
        self._deck.set_backup_status(status.state, status.child)

    def _backup_problem(self, project_name: str, message: str) -> None:
        """A backup failure a parent has to see -- in practice, a blocked credential.

        Section 29A requires notifying the parent when secret scanning blocks a push.
        Everything else the queue handles silently: a child must not be interrupted by
        GitHub, and an ordinary offline retry is not news.
        """
        QMessageBox.warning(self, APP_NAME, f"{project_name}\n\n{message}")

    def _close_project(self) -> None:
        """End the conversation thread, save outstanding work, clear the crash marker.

        Memory is written before the final checkpoint so the saved version contains it.
        """
        # Before anything else, because the web engine has to be let go of in order:
        # Qt destroys a profile whose page is still alive with "Expect troubles!", and
        # the trouble is a crash. Closing a parent widget does not call closeEvent on
        # its children, so the Workbench has to be asked.
        if self._workbench is not None:
            self._workbench.release()
        if self._controller is not None:
            self._controller.close()
            self._controller = None
        project = self._versions.project if self._versions is not None else None
        if self._versions is not None:
            self._versions.finish()
            self._versions = None
        # After the final checkpoint, so the backup includes it. Section 29A's chain
        # ends in a push, and closing a project is the last chance to start one.
        if project is not None:
            self._sync.flush(project)

    def closeEvent(self, event) -> None:
        self._close_project()
        self._sync.stop()
        # The launch-path worker, and the one place Phase 11's rule was not applied.
        # ``_start_model_load`` starts this on every launch and a 4B model takes about a
        # second to load, so closing the window in that first second destroyed a running
        # QThread and aborted the process -- measured at exit 134, with a macOS crash
        # report. "If you add a worker, wait for it on the way out" (HANDOFF section 4).
        stop_thread(self._loader_thread)
        self._loader_thread = None
        super().closeEvent(event)
