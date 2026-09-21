"""Settings, including Parent Settings and Advanced.

WORKORDER_01 section 32 names the sections; sections 22, 24 and 25 say what goes in the
parent ones. Three things about how this is built are deliberate.

**The permission rows are generated from data.** ``permissions.GATES`` describes each
control and this renders whatever is in it, so Phase 7 can give ``arduino_upload`` a
consumer without touching this file -- the same rule ``profiles.json`` and
``models.json`` already follow.

**Every control is a combo box, including the on/off ones.** Not a house style: section
35A step 6 shows the parent page as a list of *values* ("Cloud AI: OFF", "Package
installation: Ask Parent"), a three-state permission needs a chooser anyway, and
``theme.py`` styles ``QComboBox`` while it does not style ``QCheckBox``. One control type
means one visual treatment in both light and dark.

**Parent Settings is behind the PIN, and says so when there is not one.** Until the
Phase 8 wizard collects a PIN there is nothing to check, so the page opens -- and states
plainly that anyone using this Mac can change it. An interface that implies a lock it
does not have is worse than one that admits it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opennest import APP_NAME, __version__, diagnostics, paths
from opennest.ai import router
from opennest.ai.provider import ProviderError
from opennest.projects.manager import list_projects
from opennest.security import keychain, permissions
from opennest.ui import consent
from opennest.ui.common import horizontal_rule, mono_label, section_label

#: WORKORDER_01 section 32's list, in its order.
PAGES = ("General", "Local AI", "Cloud AI", "Parent Settings", "Projects", "Advanced")

PARENT_PAGE = "Parent Settings"


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "cardBody")
    label.setWordWrap(True)
    return label


def _page() -> tuple[QWidget, QVBoxLayout]:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return widget, layout


def _scrolled(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setWidget(widget)
    return area


class SettingsWindow(QDialog):
    """One window, six sections. Emits :attr:`changed` when a parent control moves."""

    changed = Signal()

    def __init__(
        self,
        parent=None,
        *,
        controls: permissions.ParentControls | None = None,
        credentials: keychain.Credentials | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Settings")
        self.resize(720, 520)
        self.controls = controls if controls is not None else permissions.current()
        self.credentials = credentials or keychain.default()
        #: Set once the PIN has been accepted, so a parent is asked once per window.
        self._unlocked = False
        self._previous_row = 0
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)

        split = QHBoxLayout()
        split.setSpacing(12)

        self._nav = QListWidget()
        self._nav.setFixedWidth(160)
        for name in PAGES:
            self._nav.addItem(name)
        self._nav.currentRowChanged.connect(self._page_selected)

        self._stack = QStackedWidget()
        self._stack.addWidget(_scrolled(self._general_page()))
        self._stack.addWidget(_scrolled(self._local_ai_page()))
        self._stack.addWidget(_scrolled(self._cloud_ai_page()))
        self._stack.addWidget(_scrolled(self._parent_page()))
        self._stack.addWidget(_scrolled(self._projects_page()))
        self._stack.addWidget(_scrolled(self._advanced_page()))

        split.addWidget(self._nav)
        split.addWidget(self._stack, 1)
        outer.addLayout(split, 1)

        outer.addWidget(horizontal_rule())
        footer = QHBoxLayout()
        done = QPushButton("Done")
        done.setProperty("role", "primary")
        done.clicked.connect(self.accept)
        footer.addStretch(1)
        footer.addWidget(done)
        outer.addLayout(footer)

        self._nav.setCurrentRow(0)

    # -- pages --------------------------------------------------------------

    def _general_page(self) -> QWidget:
        widget, layout = _page()
        layout.addWidget(section_label("General"))
        layout.addWidget(_body(f"{APP_NAME} {__version__}"))
        layout.addWidget(_body(
            "Open Nest works entirely on this Mac. Cloud AI is an option a parent can "
            "turn on, and it is off until they do."
        ))
        layout.addWidget(horizontal_rule())
        layout.addWidget(section_label("Where things are kept"))
        layout.addWidget(mono_label(paths.paths_report()))
        layout.addStretch(1)
        return widget

    def _local_ai_page(self) -> QWidget:
        widget, layout = _page()
        layout.addWidget(section_label("Local AI"))
        layout.addWidget(_body("These run on this Mac. They need no internet."))
        for entry in router.local_models():
            layout.addWidget(self._model_row(entry))
        layout.addWidget(horizontal_rule())
        layout.addWidget(mono_label(f"Models are stored in {paths.models_dir()}"))
        layout.addStretch(1)
        return widget

    def _cloud_ai_page(self) -> QWidget:
        """What the child can see about cloud AI. Changing it is a parent's job."""
        widget, layout = _page()
        layout.addWidget(section_label("Cloud AI"))
        state = "ON" if self.controls.allow_cloud_ai else "OFF"
        self._cloud_state_label = mono_label(f"CLOUD  {state}")
        layout.addWidget(self._cloud_state_label)
        layout.addWidget(_body(
            "Cloud AI uses the internet, and may cost money. A parent turns it on in "
            "Parent Settings and adds the API key there."
        ))
        layout.addWidget(horizontal_rule())
        layout.addWidget(section_label("Internet"))
        for entry in router.cloud_models():
            layout.addWidget(self._model_row(entry))
        layout.addStretch(1)
        return widget

    def _model_row(self, entry: router.ModelEntry) -> QWidget:
        """One catalogue row, saying plainly what it is and why it may be unusable.

        DESIGN_DOC section 13 forbids presenting cloud models as better than local
        ones, so nothing here says "powerful", "pro" or "premium" -- a row states where
        the model runs and, if it cannot be used, what is missing.
        """
        row = QWidget()
        box = QVBoxLayout(row)
        box.setContentsMargins(0, 4, 0, 4)
        box.setSpacing(1)

        where = "Internet" if entry.info.requires_internet else "On this Mac"
        title = QLabel(f"{entry.info.name}  —  {where}")
        title.setProperty("role", "cardTitle")
        box.addWidget(title)

        detail = [entry.info.description]
        if entry.recommended:
            detail.append("Recommended")
        if entry.license:
            detail.append(entry.license)
        if entry.download_gb:
            detail.append(f"{entry.download_gb} GB")
        box.addWidget(mono_label("   ".join(part for part in detail if part)))

        reason = router.why_unavailable(
            entry,
            allow_cloud=self.controls.cloud_allowed(),
            credentials=self.credentials,
        )
        if reason:
            box.addWidget(_body(reason))
        return row

    def _parent_page(self) -> QWidget:
        widget, layout = _page()
        self._parent_layout = layout

        layout.addWidget(section_label("Parent Settings"))
        self._lock_note = _body("")
        layout.addWidget(self._lock_note)

        layout.addWidget(horizontal_rule())
        layout.addWidget(section_label("Cloud AI"))
        layout.addWidget(_body(
            "Turning cloud AI off stops all OpenAI and Anthropic requests. It does not "
            "delete the saved keys."
        ))
        self._cloud_switch = self._switch_row(
            layout, "Allow cloud AI", self.controls.allow_cloud_ai, self._cloud_toggled
        )
        self._ask_switch = self._switch_row(
            layout, "Ask before using cloud AI",
            self.controls.ask_before_cloud_ai, self._ask_toggled,
        )

        layout.addWidget(horizontal_rule())
        keys_header = QHBoxLayout()
        keys_header.addWidget(section_label("API Keys"))
        keys_header.addStretch(1)
        explain = QPushButton("What is an API key?")
        explain.clicked.connect(lambda: consent.explain_api_keys(self))
        keys_header.addWidget(explain)
        layout.addLayout(keys_header)

        self._key_rows: dict[str, QLabel] = {}
        for status in self.credentials.statuses():
            layout.addWidget(self._key_row(status))

        layout.addWidget(horizontal_rule())
        layout.addWidget(section_label("What projects may do"))
        self._gate_boxes: dict[str, QComboBox] = {}
        for gate in permissions.GATES:
            layout.addWidget(self._gate_row(gate))

        layout.addWidget(horizontal_rule())
        layout.addWidget(section_label("Parent PIN"))
        self._pin_note = _body("")
        layout.addWidget(self._pin_note)
        pin_row = QHBoxLayout()
        set_pin = QPushButton("Set PIN")
        set_pin.clicked.connect(self._set_pin)
        clear_pin = QPushButton("Remove PIN")
        clear_pin.clicked.connect(self._clear_pin)
        pin_row.addWidget(set_pin)
        pin_row.addWidget(clear_pin)
        pin_row.addStretch(1)
        layout.addLayout(pin_row)

        layout.addStretch(1)
        self._refresh_parent_notes()
        return widget

    def _projects_page(self) -> QWidget:
        widget, layout = _page()
        layout.addWidget(section_label("Projects"))
        layout.addWidget(mono_label(str(paths.projects_root())))
        try:
            count = len(list_projects())
        except OSError:
            count = 0
        layout.addWidget(_body(f"{count} project{'' if count == 1 else 's'}."))
        layout.addStretch(1)
        return widget

    def _advanced_page(self) -> QWidget:
        widget, layout = _page()
        layout.addWidget(section_label("Advanced"))
        layout.addWidget(_body(
            "Technical information for troubleshooting. Nothing here needs changing "
            "for normal use."
        ))
        layout.addWidget(horizontal_rule())

        self._diagnostics = QPlainTextEdit()
        self._diagnostics.setReadOnly(True)
        self._diagnostics.setProperty("role", "mono")
        self._diagnostics.setPlainText(self._diagnostic_text())
        layout.addWidget(self._diagnostics, 1)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(
            lambda: self._diagnostics.setPlainText(self._diagnostic_text())
        )
        export = QPushButton("Export Diagnostic Log")
        export.clicked.connect(self._export_diagnostics)
        buttons.addWidget(refresh)
        buttons.addWidget(export)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return widget

    # -- rows ---------------------------------------------------------------

    def _switch_row(self, layout, label: str, value: bool, handler) -> QComboBox:
        row = QHBoxLayout()
        caption = QLabel(label)
        caption.setProperty("role", "cardTitle")
        box = QComboBox()
        box.addItem("On", True)
        box.addItem("Off", False)
        box.setCurrentIndex(0 if value else 1)
        box.currentIndexChanged.connect(lambda _index, b=box: handler(b.currentData()))
        row.addWidget(caption, 1)
        row.addWidget(box)
        layout.addLayout(row)
        return box

    def _gate_row(self, gate: permissions.Gate) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(1)

        row = QHBoxLayout()
        caption = QLabel(gate.label)
        caption.setProperty("role", "cardTitle")
        box = QComboBox()
        for state in permissions.STATES:
            if state == permissions.ASK and not gate.supports_ask:
                continue
            box.addItem(permissions.STATE_LABELS[state], state)
        current = self.controls.state(gate.name)
        box.setCurrentIndex(max(0, box.findData(current)))
        box.currentIndexChanged.connect(
            lambda _index, g=gate.name, b=box: self._gate_changed(g, b.currentData())
        )
        row.addWidget(caption, 1)
        row.addWidget(box)
        outer.addLayout(row)
        outer.addWidget(_body(gate.explanation))

        self._gate_boxes[gate.name] = box
        return widget

    def _key_row(self, status: keychain.ProviderStatus) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 2, 0, 2)

        caption = QLabel(status.label)
        caption.setProperty("role", "cardTitle")
        state = mono_label(status.summary)
        self._key_rows[status.provider] = state

        add = QPushButton("Replace Key" if status.configured else "Add API Key")
        add.clicked.connect(lambda _checked=False, p=status.provider: self._add_key(p))
        test = QPushButton("Test Connection")
        test.setEnabled(status.configured)
        test.clicked.connect(lambda _checked=False, p=status.provider: self._test_key(p))
        remove = QPushButton("Remove")
        remove.setEnabled(status.configured)
        remove.clicked.connect(lambda _checked=False, p=status.provider: self._remove_key(p))

        row.addWidget(caption)
        row.addWidget(state, 1)
        row.addWidget(add)
        row.addWidget(test)
        row.addWidget(remove)
        return widget

    # -- behaviour ----------------------------------------------------------

    def _page_selected(self, row: int) -> None:
        if row < 0:
            return
        if PAGES[row] == PARENT_PAGE and not self._unlock():
            # Refused: go back rather than leaving the parent page selected but blank.
            self._nav.setCurrentRow(self._previous_row)
            return
        self._previous_row = row
        self._stack.setCurrentIndex(row)

    def _unlock(self) -> bool:
        if self._unlocked:
            return True
        if consent.ask_parent_pin(
            self, self.credentials, reason="Parent Settings"
        ):
            self._unlocked = True
            return True
        return False

    def _save(self) -> None:
        try:
            self.controls.save()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        permissions.reload()
        self.changed.emit()

    def _cloud_toggled(self, value: bool) -> None:
        self.controls.allow_cloud_ai = bool(value)
        self._save()
        self._cloud_state_label.setText(f"CLOUD  {'ON' if value else 'OFF'}")

    def _ask_toggled(self, value: bool) -> None:
        self.controls.ask_before_cloud_ai = bool(value)
        self._save()

    def _gate_changed(self, name: str, state: str) -> None:
        self.controls.set_state(name, state)
        self._save()

    def _add_key(self, provider: str) -> None:
        label = keychain.PROVIDER_LABELS.get(provider, provider)
        key, accepted = QInputDialog.getText(
            self,
            f"{label} API Key",
            f"Paste the {label} API key.\n\n"
            f"It is stored in the macOS Keychain and never written into a project, "
            f"a setting or a log.",
            QLineEdit.EchoMode.Password,
        )
        if not accepted or not key.strip():
            return
        try:
            self.credentials.save_key(provider, key)
        except keychain.CredentialError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._refresh_keys()

    def _remove_key(self, provider: str) -> None:
        label = keychain.PROVIDER_LABELS.get(provider, provider)
        confirm = QMessageBox.question(
            self, APP_NAME, f"Remove the {label} API key from the Keychain?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.credentials.delete_key(provider)
        except keychain.CredentialError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._refresh_keys()

    def _test_key(self, provider: str) -> None:
        """Section 2258's "Test Connection". The only outbound request Settings makes."""
        entry = next(
            (e for e in router.cloud_models() if e.info.provider == provider), None
        )
        if entry is None:
            QMessageBox.warning(self, APP_NAME, f"No {provider} model is configured.")
            return
        try:
            built = router.build_provider(
                entry.info.id, allow_cloud=True, credentials=self.credentials
            )
            message = built.check_connection()
        except ProviderError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        QMessageBox.information(self, APP_NAME, message)

    def _refresh_keys(self) -> None:
        for status in self.credentials.statuses():
            label = self._key_rows.get(status.provider)
            if label is not None:
                label.setText(status.summary)
        self.changed.emit()

    def _set_pin(self) -> None:
        pin, accepted = QInputDialog.getText(
            self, "Parent PIN",
            "Choose a parent PIN.\n\nOnly the PIN's fingerprint is stored, never the "
            "PIN itself.",
            QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        again, accepted = QInputDialog.getText(
            self, "Parent PIN", "Type it again.", QLineEdit.EchoMode.Password
        )
        if not accepted:
            return
        if pin != again:
            QMessageBox.warning(self, APP_NAME, "Those did not match. Nothing changed.")
            return
        try:
            self.credentials.set_parent_pin(pin)
        except keychain.CredentialError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._unlocked = True
        self._refresh_parent_notes()

    def _clear_pin(self) -> None:
        if not self.credentials.parent_pin_set():
            return
        if not consent.ask_parent_pin(self, self.credentials, reason="Remove parent PIN"):
            return
        try:
            self.credentials.clear_parent_pin()
        except keychain.CredentialError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._refresh_parent_notes()

    def _refresh_parent_notes(self) -> None:
        if self.credentials.parent_pin_set():
            self._lock_note.setText("These settings are protected by the parent PIN.")
            self._pin_note.setText("A PIN is set.")
        else:
            self._lock_note.setText(
                "No parent PIN is set, so anyone using this Mac can change these."
            )
            self._pin_note.setText("No PIN is set.")

    def _diagnostic_text(self) -> str:
        try:
            return diagnostics.report(self.controls, self.credentials)
        except Exception as exc:  # A report that cannot be built should say so.
            return f"The diagnostic report could not be built: {type(exc).__name__}"

    def _export_diagnostics(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self, "Export Diagnostic Log",
            str(paths.logs_dir() / "open-nest-diagnostics.txt"),
            "Text files (*.txt)",
        )
        if not name:
            return
        try:
            diagnostics.write_report(
                name, controls=self.controls, credentials=self.credentials
            )
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"That could not be saved: {exc}")
            return
        QMessageBox.information(self, APP_NAME, f"Saved to {name}")


def open_settings(parent, **kwargs) -> SettingsWindow:
    """Show Settings modally and return the window, so a caller can read what changed."""
    window = SettingsWindow(parent, **kwargs)
    window.setWindowModality(Qt.WindowModality.ApplicationModal)
    window.exec()
    return window
