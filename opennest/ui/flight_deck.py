"""Flight Deck -- the Open Nest home screen.

DESIGN_DOC.md section 10. Simple and spacious: what do you want to make, what have you
made before, and is the AI ready. "Flight Deck" is a quiet internal name, not a theme --
there are no aviation graphics here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from opennest import APP_NAME
from opennest.ai import images
from opennest.projects.manager import Project, list_projects
from opennest.projects.profiles import Profile, load_profiles
from opennest.ui.common import (
    ClickableFrame,
    horizontal_rule,
    section_label,
    status_row,
)


def _short(reason: str | None) -> str | None:
    """The first line of a reason -- a card has room for a sentence, not a paragraph."""
    if not reason:
        return None
    return reason.strip().splitlines()[0]


def greeting(name: str | None, now: datetime | None = None) -> str:
    """"Good evening, Elliot." Calm and short, per DESIGN_DOC section 20."""
    hour = (now or datetime.now()).hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {name}." if name else f"Good {part}."


class ProfileCard(ClickableFrame):
    """One choice of thing to make. A bordered panel, not a floating card.

    A profile that cannot be used right now is shown anyway, dimmed, with the reason --
    the same choice Phase 6 made for cloud models in the picker. Hiding Image Creation
    when cloud is off leaves a parent hunting for a feature they were told exists;
    showing it greyed out with "needs OpenAI turned on" tells them what to do.
    """

    def __init__(self, profile: Profile, unavailable_reason: str | None = None) -> None:
        super().__init__("profileCard")
        self.profile = profile
        self.unavailable_reason = unavailable_reason
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        name = QLabel(profile.name.upper())
        name.setProperty("role", "cardTitle")
        tagline = QLabel(unavailable_reason or profile.tagline)
        tagline.setProperty("role", "cardBody")

        layout.addWidget(name)
        layout.addWidget(tagline)

        if unavailable_reason:
            self.setEnabled(False)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setToolTip(unavailable_reason)


class RecentProjectRow(ClickableFrame):
    def __init__(self, project: Project) -> None:
        super().__init__("recentRow")
        self.project = project

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        name = QLabel(project.name)
        name.setProperty("role", "cardTitle")
        kind = QLabel(project.profile.name)
        kind.setProperty("role", "mono")
        layout.addWidget(name)
        layout.addStretch(1)
        layout.addWidget(kind)


class FlightDeck(QWidget):
    """Home. Emits the profile chosen for a new project, or an existing project to open."""

    new_project_requested = Signal(object)   # Profile
    project_opened = Signal(object)          # Project
    settings_requested = Signal()

    def __init__(
        self,
        user_name: str | None = None,
        *,
        allow_cloud: bool = False,
        credentials=None,
    ) -> None:
        super().__init__()
        self.user_name = user_name
        #: Needed to say whether a profile that requires a cloud provider can be used.
        #: Only ever asked whether a key exists, never for its value.
        self.allow_cloud = allow_cloud
        self.credentials = credentials
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 30, 36, 28)
        layout.setSpacing(4)

        wordmark = QLabel(APP_NAME.upper())
        wordmark.setProperty("role", "wordmark")
        deck = QLabel("FLIGHT DECK")
        deck.setProperty("role", "descriptor")

        masthead = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(wordmark)
        titles.addWidget(deck)
        settings = QPushButton("Settings")
        settings.clicked.connect(self.settings_requested.emit)
        masthead.addLayout(titles)
        masthead.addStretch(1)
        masthead.addWidget(settings, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(masthead)
        layout.addSpacing(26)

        hello = QLabel(greeting(self.user_name))
        hello.setProperty("role", "greeting")
        question = QLabel("What do you want to make?")
        question.setProperty("role", "question")
        layout.addWidget(hello)
        layout.addWidget(question)
        layout.addSpacing(16)

        self._profile_area = QVBoxLayout()
        self._profile_area.setSpacing(4)
        layout.addLayout(self._profile_area)
        self.refresh_profiles()

        layout.addSpacing(26)
        self._recent_area = QVBoxLayout()
        self._recent_area.setSpacing(4)
        layout.addWidget(section_label("Recent Projects"))
        layout.addSpacing(6)
        layout.addLayout(self._recent_area)

        layout.addStretch(1)
        layout.addWidget(horizontal_rule())
        layout.addSpacing(10)
        self._status = status_row("Local AI", "idle", "Checking")
        layout.addWidget(self._status)
        # DESIGN_DOC section 14 shows CLOUD as its own status line, and section 34 wants
        # the internet/on-this-Mac distinction visible without opening anything.
        self._cloud_status = status_row("Cloud", "idle", "Off")
        layout.addWidget(self._cloud_status)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.refresh()

    def refresh_profiles(self) -> None:
        """Rebuild the profile cards, so a parent turning cloud on takes effect here."""
        while self._profile_area.count():
            item = self._profile_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for profile in load_profiles():
            reason = images.unmet_requirements(
                profile, allow_cloud=self.allow_cloud, credentials=self.credentials
            )
            card = ProfileCard(profile, unavailable_reason=_short(reason))
            if reason is None:
                card.clicked.connect(lambda p=profile: self.new_project_requested.emit(p))
            self._profile_area.addWidget(card)

    def refresh(self) -> None:
        """Reload the recent-project list from disk."""
        while self._recent_area.count():
            item = self._recent_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        projects = list_projects()[:6]
        if not projects:
            # brand_design_guide.md section 14's "No Projects", in its own words. The
            # profile cards are directly above, so "start with an idea" points at them
            # without having to say "above".
            empty = QLabel("Nothing here yet.\nStart with an idea.")
            empty.setProperty("role", "cardBody")
            self._recent_area.addWidget(empty)
            return
        for project in projects:
            row = RecentProjectRow(project)
            row.clicked.connect(lambda p=project: self.project_opened.emit(p))
            self._recent_area.addWidget(row)

    def set_model_status(self, state: str, text: str) -> None:
        self._status = self._replace_status(self._status, "Local AI", state, text)

    def set_cloud_status(self, state: str, text: str) -> None:
        self._cloud_status = self._replace_status(
            self._cloud_status, "Cloud", state, text
        )

    def _replace_status(self, existing, name: str, state: str, text: str):
        parent = existing.parentWidget()
        layout = parent.layout() if parent else None
        replacement = status_row(name, state, text)
        if layout is None:
            return existing
        layout.replaceWidget(existing, replacement)
        existing.deleteLater()
        return replacement


def connect_new_project(deck: FlightDeck, handler: Callable[[Profile], None]) -> None:
    deck.new_project_requested.connect(handler)
