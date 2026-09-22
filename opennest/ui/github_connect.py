"""The GitHub sign-in window -- WORKORDER_01 section 35A's "GitHub connection flow".

The work order writes the screen out almost exactly:

    Connect GitHub

    1. A GitHub sign-in window will open.
    2. Sign in to the parent's GitHub account.
    3. Approve Build Lab.
    4. Return here.

    [ Connect GitHub ]

With device flow the browser is the sign-in window, and there is a code to carry across.
Two constraints shape the implementation:

**Polling happens on a timer, not in a loop.** A parent is off in another application
for as long as it takes them to find their password, and ``auth.wait_for_approval``
would block the GUI thread for the whole of it. So this asks once per interval from a
``QTimer`` and stays responsive and cancellable throughout -- the same reason
``setup/downloader.py`` polls a queue rather than waiting on a subprocess.

**Cancelling is not a failure.** A parent who changes their mind gets the dialog closed
and nothing saved, not an error about an incomplete sign-in.
"""

from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from opennest import APP_NAME
from opennest.github import auth
from opennest.github.transport import GitHubError
from opennest.github.transport import default as default_transport
from opennest.ui.common import section_label


class ConnectGitHubDialog(QDialog):
    """Runs the device flow in front of a parent. ``login`` is set on success."""

    def __init__(self, parent, *, credentials, transport=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect GitHub")
        self.setMinimumWidth(460)
        self.credentials = credentials
        self.transport = transport if transport is not None else default_transport()
        self.login = ""
        self._code: auth.DeviceCode | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(section_label("Connect GitHub"))

        self._steps = QLabel(
            "Open Nest will back up projects to a private repository on the parent's "
            "GitHub account.\n\n"
            "Nothing is made public, and the child never has to sign in to anything."
        )
        self._steps.setWordWrap(True)
        layout.addWidget(self._steps)

        # The code a parent reads off the screen and types into GitHub. Phase 9's smoke
        # test found this styled with ``mono_label`` -- 11 px in the muted text colour,
        # so the focal element of the screen rendered *smaller and greyer* than the body
        # text around it. It gets its own role instead (SPIKES.md 17F, defect 3).
        self._code_label = QLabel("")
        self._code_label.setProperty("role", "deviceCode")
        self._code_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._code_label.setVisible(False)
        layout.addWidget(self._code_label)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._connect = QPushButton("Connect GitHub")
        self._connect.clicked.connect(self._begin)
        self._copy = QPushButton("Copy code")
        self._copy.setVisible(False)
        self._copy.clicked.connect(self._copy_code)
        self._open = QPushButton("Open GitHub again")
        self._open.setVisible(False)
        self._open.clicked.connect(self._open_browser)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        buttons.addWidget(self._connect)
        buttons.addWidget(self._copy)
        buttons.addWidget(self._open)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    # -- the flow -----------------------------------------------------------

    def _begin(self) -> None:
        if not auth.configured():
            self._fail(
                "This version of Open Nest was not built with GitHub backup, so there "
                "is nothing to connect to."
            )
            return
        self._connect.setEnabled(False)
        self._status.setText("Asking GitHub for a sign-in code...")
        try:
            self._code = auth.begin(self.transport)
        except GitHubError as exc:
            self._fail(str(exc))
            return

        self._code_label.setText(self._code.user_code)
        self._code_label.setVisible(True)
        self._copy.setVisible(True)
        self._open.setVisible(True)
        # Connect has done its job. Leaving it on screen disabled cost the button row
        # more width than the dialog had, which is what clipped "Open GitHub again" into
        # "Open GitHub agai" (SPIKES.md 17F, defect 1).
        self._connect.setVisible(False)
        # The steps deliberately do *not* use ``DeviceCode.instructions``: that property
        # carries the code inline in step 3, so the standalone label above read as a
        # repetition of it rather than as the thing to read (defect 2). The wording lives
        # here rather than in ``github/auth.py`` because it is presentation, and the
        # protocol layer has no other reason to change. ``instructions`` is left as it is.
        self._steps.setText(
            f"1. Open {self._code.verification_uri} in a browser.\n"
            "2. Sign in to the parent's GitHub account.\n"
            "3. Enter the code above.\n"
            "4. Approve Open Nest, then come back here."
        )
        self._status.setText("Waiting for the sign-in to be approved...")
        self._open_browser()
        self._timer.start(max(self._code.interval, auth.MINIMUM_INTERVAL) * 1000)

    def _poll(self) -> None:
        if self._code is None:
            return
        try:
            outcome = auth.poll(self._code, self.transport, self.credentials)
        except GitHubError as exc:
            self._timer.stop()
            self._fail(str(exc))
            return

        if isinstance(outcome, auth.Pending):
            # GitHub can ask to be asked less often.
            self._timer.setInterval(outcome.interval * 1000)
            return

        self._timer.stop()
        self.login = outcome.login
        self.accept()

    # -- helpers ------------------------------------------------------------

    def _open_browser(self) -> None:
        if self._code is None:
            return
        try:
            webbrowser.open(self._code.verification_uri)
        except Exception:  # noqa: BLE001 - a browser that will not open is not fatal
            self._status.setText(
                f"Open {self._code.verification_uri} by hand and enter the code above."
            )

    def _copy_code(self) -> None:
        if self._code is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._code.user_code)
            self._status.setText("Code copied. Paste it into GitHub, then come back.")

    def _fail(self, message: str) -> None:
        # Offer Connect again, which means putting it back on screen as well as
        # re-enabling it -- ``_begin`` hides it once the flow is under way.
        self._connect.setVisible(True)
        self._connect.setEnabled(True)
        self._status.setText("")
        QMessageBox.warning(self, APP_NAME, message)


def connect_github(parent, *, credentials, transport=None) -> str:
    """Show the dialog. Returns the connected account's login, or "" if not connected."""
    dialog = ConnectGitHubDialog(parent, credentials=credentials, transport=transport)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.login
    return ""
