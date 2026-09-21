"""The two windows the update protocol shows a parent.

Separate from :mod:`opennest.setup.migration` and :mod:`opennest.setup.updates` for the
reason the rest of this package is split that way: the decisions are UI-free and
testable, and this file only puts them on screen.

- :func:`run_migration` is WORKORDER_01's *"Build Lab was updated. A few components need
  to be refreshed. [ Update Build Lab ]"*, shown on the launch after a ``git pull``.
- :func:`show_update_check` is decision D9's parent-facing "Check for Updates", which
  reports and never touches the checkout.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from opennest import APP_NAME
from opennest.setup import migration, updates
from opennest.setup.state import InstallationState
from opennest.ui.common import horizontal_rule, section_label


class MigrationDialog(QDialog):
    """Shown before the app opens, when a pull moved something."""

    def __init__(self, state: InstallationState, plan: migration.MigrationPlan, parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(460)
        self.state = state
        self.plan = plan
        self.applied = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        headline = QLabel(plan.headline())
        headline.setProperty("role", "greeting")
        headline.setWordWrap(True)
        layout.addWidget(headline)
        layout.addWidget(horizontal_rule())

        layout.addWidget(section_label("What changed"))
        detail = QLabel("\n\n".join(plan.lines()))
        detail.setProperty("role", "cardBody")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        keep = QLabel(
            "Your projects, their saved versions, what they remember, and any API keys "
            "are not touched."
        )
        keep.setProperty("role", "cardBody")
        keep.setWordWrap(True)
        layout.addWidget(keep)

        self._status = QLabel("")
        self._status.setProperty("role", "mono")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate; pip does not report a percentage
        self._bar.hide()
        layout.addWidget(self._bar)

        layout.addWidget(horizontal_rule())
        buttons = QHBoxLayout()
        self._later = QPushButton("Not Now")
        self._later.clicked.connect(self.reject)
        self._update = QPushButton(f"Update {APP_NAME}")
        self._update.setProperty("role", "primary")
        self._update.clicked.connect(self._apply)
        buttons.addStretch(1)
        buttons.addWidget(self._later)
        buttons.addWidget(self._update)
        layout.addLayout(buttons)

    def _apply(self) -> None:
        self._update.setEnabled(False)
        self._later.setEnabled(False)
        self._bar.show()
        # Applying is pip, which is slow but not interactive. Processing events keeps
        # the window painted rather than letting macOS grey it out as unresponsive.
        QApplication.processEvents()

        result = migration.apply(self.state, self.plan, on_progress=self._say)
        self._bar.hide()
        self.applied = result.ok
        if not result.ok:
            self._status.setText(result.message)
            self._later.setText("Continue Anyway")
            self._later.setEnabled(True)
            return
        self.accept()

    def _say(self, message: str) -> None:
        self._status.setText(message)
        QApplication.processEvents()


def run_migration(state: InstallationState, plan: migration.MigrationPlan) -> bool:
    """Show the migration prompt. Returns whether it was applied.

    Declining is allowed and is not an error: the app opens either way, and the next
    launch asks again because the fingerprint was not adopted.
    """
    dialog = MigrationDialog(state, plan)
    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    if accepted and plan.models_to_refresh:
        # The one thing migration will not do for a parent, said plainly afterwards.
        QMessageBox.information(
            dialog, APP_NAME,
            "One more thing:\n\n" + "\n\n".join(plan.models_to_refresh)
            + "\n\nYou can download it from Settings when you are ready.",
        )
    return accepted and dialog.applied


def show_update_check(parent) -> updates.UpdateStatus:
    """Decision D9's "Check for Updates", from Settings.

    Contacts the remote, reports, and changes nothing. There is no button here that
    pulls: that is a separate product feature, and this deliberately stops short of it.
    """
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        status = updates.check()
    finally:
        QApplication.restoreOverrideCursor()

    box = QMessageBox(parent)
    box.setWindowTitle(f"{APP_NAME} Updates")
    box.setText(status.summary)
    if status.detail:
        box.setInformativeText(status.detail)
    box.exec()
    return status
