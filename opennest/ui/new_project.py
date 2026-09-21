"""Naming a new project, and picking an idea to start from.

WORKORDER_01 section 27: every profile offers idea cards. Section 5 calls the same list
"suggested starter prompts", and that second name is the useful one -- an idea card is
only worth having if picking it actually starts something. So a chosen card becomes the
first thing said to the Assistant, filled into the message box rather than sent, because
a child who picked "Maze" almost always wants to add a word or two before it runs.

Blank deliberately has no ideas: section 27 lists none for it, and the whole point of
"Start with an idea" is that the idea is theirs. The card area simply does not appear.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from opennest.projects.profiles import Profile
from opennest.ui.common import ClickableFrame, section_label


@dataclass(frozen=True)
class NewProject:
    """What the dialog collected."""

    name: str
    starter_idea: str | None = None


class IdeaCard(ClickableFrame):
    """One suggestion. Clicking it names the project and seeds the first message."""

    def __init__(self, idea: str) -> None:
        super().__init__("profileCard")
        self.idea = idea
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)
        title = QLabel(idea)
        title.setProperty("role", "cardTitle")
        layout.addWidget(title)


class NewProjectDialog(QDialog):
    """Name it, and optionally start from one of the profile's ideas."""

    def __init__(self, parent, profile: Profile) -> None:
        super().__init__(parent)
        self.profile = profile
        self.chosen_idea: str | None = None
        self.setWindowTitle("New Project")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        question = QLabel(f"What should we call your {profile.name.lower()}?")
        question.setProperty("role", "question")
        layout.addWidget(question)

        self._name = QLineEdit()
        self._name.setPlaceholderText("My project")
        self._name.textChanged.connect(self._name_changed)
        layout.addWidget(self._name)

        if profile.starter_ideas:
            layout.addSpacing(10)
            layout.addWidget(section_label("Or start from an idea"))
            for idea in profile.starter_ideas:
                card = IdeaCard(idea)
                card.clicked.connect(lambda chosen=idea: self._pick(chosen))
                layout.addWidget(card)

        self._chosen_label = QLabel()
        self._chosen_label.setProperty("role", "mono")
        self._chosen_label.hide()
        layout.addWidget(self._chosen_label)

        layout.addSpacing(8)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._name_changed()

    def _name_changed(self) -> None:
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self._name.text().strip()))

    def _pick(self, idea: str) -> None:
        """Take the idea, and use it as the name if they have not typed one."""
        self.chosen_idea = idea
        if not self._name.text().strip():
            self._name.setText(idea)
        self._chosen_label.setText(f"Starting from: {idea}")
        self._chosen_label.show()

    def result_value(self) -> NewProject | None:
        name = self._name.text().strip()
        if not name:
            return None
        return NewProject(name=name, starter_idea=self.chosen_idea)


def ask(parent, profile: Profile) -> NewProject | None:
    """Show the dialog. None means they cancelled or gave no name."""
    dialog = NewProjectDialog(parent, profile)
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.result_value()
    finally:
        dialog.deleteLater()
