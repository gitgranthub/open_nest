"""Naming a new project, choosing what it starts from, and picking an idea.

WORKORDER_01 section 27: every profile offers idea cards. Section 5 calls the same list
"suggested starter prompts", and that second name is the useful one -- an idea card is
only worth having if picking it actually starts something. So a chosen card becomes the
first thing said to Gary, filled into the message box rather than sent, because
a child who picked "Maze" almost always wants to add a word or two before it runs.

Blank deliberately has no ideas: section 27 lists none for it, and the whole point of
"Start with an idea" is that the idea is theirs. The card area simply does not appear.

Phase 11 added the row above the ideas: what the project begins *with*. A profile's
starter kits are offered beside "Start Empty", and empty is always available -- section
61 of the Phase 11 work order asks for it and section 8 asks that the words stay the
child's ("Start Empty", "Use Starter") rather than a developer's ("scaffold",
"bootstrap", "initialize template"). Blank offers no kit at all, so the row does not
appear there either.
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

from opennest.projects import starters
from opennest.projects.profiles import Profile
from opennest.ui.common import ClickableFrame, section_label

#: What the "no starter" choice carries. Named rather than written as a bare ``None`` at
#: each site, because ``None`` here means the child chose emptiness -- which is not the
#: same as ``manager.PROFILE_DEFAULT``, the caller having chosen nothing.
START_EMPTY = None


@dataclass(frozen=True)
class NewProject:
    """What the dialog collected."""

    name: str
    starter_idea: str | None = None
    #: The kit to begin from, or ``None`` for empty. Never ``PROFILE_DEFAULT``: by the
    #: time the dialog closes the choice has actually been made.
    starter_id: str | None = None


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
        self.setAccessibleName(idea)


class StarterCard(ClickableFrame):
    """One way to begin: a kit, or nothing at all."""

    def __init__(self, starter_id: str | None, title: str, detail: str) -> None:
        super().__init__("profileCard")
        self.starter_id = starter_id
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)
        name = QLabel(title)
        name.setProperty("role", "cardTitle")
        body = QLabel(detail)
        body.setProperty("role", "cardBody")
        body.setWordWrap(True)
        layout.addWidget(name)
        layout.addWidget(body)
        self.setAccessibleName(title)
        self.setAccessibleDescription(detail)

    def set_chosen(self, chosen: bool) -> None:
        # Both states are written as literals with a rule each in theme.py, rather than
        # setting and clearing one: an unstyled property value renders in the system
        # appearance and Qt does not warn, which is what
        # ``test_every_property_a_widget_sets_is_actually_styled`` exists to catch.
        if chosen:
            self.setProperty("state", "chosen")
        else:
            self.setProperty("state", "unchosen")
        self.style().unpolish(self)
        self.style().polish(self)


class NewProjectDialog(QDialog):
    """Name it, and optionally start from one of the profile's ideas."""

    def __init__(self, parent, profile: Profile) -> None:
        super().__init__(parent)
        self.profile = profile
        self.chosen_idea: str | None = None
        #: The kit this project will begin from, or ``START_EMPTY``. Seeded from the
        #: profile's own default so the common path is one click on OK.
        self.chosen_starter: str | None = START_EMPTY
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

        self._starter_cards: list[StarterCard] = []
        offered = starters.starters_for(profile)
        if offered:
            layout.addSpacing(10)
            layout.addWidget(section_label("How it starts"))
            default = starters.default_starter(profile)
            self.chosen_starter = default.id if default else START_EMPTY
            for starter in offered:
                self._add_starter_card(layout, starter.id, starter.name,
                                       starter.description)
            self._add_starter_card(
                layout, START_EMPTY, "Start Empty",
                "No files. Say what you want and it gets written from nothing.",
            )
            self._show_choice()
        else:
            # Blank offers no kit, so there is nothing to choose between and no row.
            self.chosen_starter = START_EMPTY

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

    def _add_starter_card(self, layout, starter_id, title: str, detail: str) -> None:
        card = StarterCard(starter_id, title, detail)
        card.clicked.connect(lambda chosen=starter_id: self._pick_starter(chosen))
        layout.addWidget(card)
        self._starter_cards.append(card)

    def _pick_starter(self, starter_id: str | None) -> None:
        self.chosen_starter = starter_id
        self._show_choice()

    def _show_choice(self) -> None:
        for card in self._starter_cards:
            card.set_chosen(card.starter_id == self.chosen_starter)

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
        return NewProject(
            name=name,
            starter_idea=self.chosen_idea,
            starter_id=self.chosen_starter,
        )


def ask(parent, profile: Profile) -> NewProject | None:
    """Show the dialog. None means they cancelled or gave no name."""
    dialog = NewProjectDialog(parent, profile)
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.result_value()
    finally:
        dialog.deleteLater()
