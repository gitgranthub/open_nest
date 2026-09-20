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
from opennest.ai.router import build_provider, default_model_id
from opennest.projects.manager import Project, ProjectError, create_project
from opennest.projects.profiles import Profile
from opennest.ui.flight_deck import FlightDeck
from opennest.ui.workbench import Workbench
from opennest.ui.worker import ModelLoader, run_in_thread


class MainWindow(QMainWindow):
    def __init__(self, user_name: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)

        self._provider = None
        self._loader_thread = None
        self._workbench: Workbench | None = None

        self._stack = QStackedWidget()
        self._deck = FlightDeck(user_name)
        self._deck.new_project_requested.connect(self._new_project)
        self._deck.project_opened.connect(self._open_project)
        self._stack.addWidget(self._deck)
        self.setCentralWidget(self._stack)

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

        controller = AgentController(
            project,
            self._provider,
            Toolbox(project),
            build_style=project.manifest.build_style,
        )
        workbench = Workbench(project, controller)
        workbench.back_requested.connect(self._back_to_deck)

        if self._workbench is not None:
            self._stack.removeWidget(self._workbench)
            self._workbench.deleteLater()
        self._workbench = workbench
        self._stack.addWidget(workbench)
        self._stack.setCurrentWidget(workbench)
        if self._provider.is_loaded:
            workbench.set_model_status("ready", "Ready")

    def _back_to_deck(self) -> None:
        self._deck.refresh()
        self._stack.setCurrentWidget(self._deck)
