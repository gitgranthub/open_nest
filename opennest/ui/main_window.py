"""The Open Nest main window: Flight Deck and Workbench in one shell."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from opennest import APP_NAME
from opennest.agent.controller import AgentController
from opennest.agent.tools import Toolbox
from opennest.ai.provider import ProviderError
from opennest.ai.router import build_provider, default_model_id, get_entry, unmet_requirements
from opennest.memory.manager import MemoryManager
from opennest.projects.manager import Project, ProjectError, create_project
from opennest.projects.profiles import Profile
from opennest.security import keychain, permissions
from opennest.ui import consent
from opennest.ui import settings as settings_ui
from opennest.ui.flight_deck import FlightDeck
from opennest.ui.workbench import Workbench
from opennest.ui.worker import ModelLoader, run_in_thread
from opennest.versioning.checkpoint import VersionHistory


class MainWindow(QMainWindow):
    def __init__(self, user_name: str | None = None, *, credentials=None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

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

        self._stack = QStackedWidget()
        self._deck = FlightDeck(user_name)
        self._deck.new_project_requested.connect(self._new_project)
        self._deck.project_opened.connect(self._open_project)
        self._deck.settings_requested.connect(self._open_settings)
        self._stack.addWidget(self._deck)
        self.setCentralWidget(self._stack)

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
        loader.ready.connect(lambda: self._model_ready(True))
        loader.failed.connect(self._model_failed)
        self._loader_thread = run_in_thread(self, loader)

    def _model_ready(self, ready: bool) -> None:
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
        self._show_cloud_status()
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
        name, accepted = QInputDialog.getText(
            self, "New Project", f"What should we call your {profile.name.lower()}?"
        )
        if not accepted or not name.strip():
            return
        try:
            project = create_project(name.strip(), profile.id, model=default_model_id())
        except ProjectError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._deck.refresh()
        self._open_project(project)

    def _open_project(self, project: Project) -> None:
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

        versions = VersionHistory(project)
        versions.start()
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

    def _back_to_deck(self) -> None:
        self._close_project()
        self._deck.refresh()
        self._stack.setCurrentWidget(self._deck)

    def _close_project(self) -> None:
        """End the conversation thread, save outstanding work, clear the crash marker.

        Memory is written before the final checkpoint so the saved version contains it.
        """
        if self._controller is not None:
            self._controller.close()
            self._controller = None
        if self._versions is not None:
            self._versions.finish()
            self._versions = None

    def closeEvent(self, event) -> None:
        self._close_project()
        super().closeEvent(event)
