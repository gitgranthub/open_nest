"""The Open Nest main window.

Phase 0 placeholder: enough structure to confirm the theme renders correctly. The Flight
Deck (recent projects, new project, status) arrives in Phase 2.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from opennest import APP_NAME


def section_label(text: str) -> QLabel:
    """An uppercase equipment-style header: PROJECT, ASSETS, LOCAL AI."""
    label = QLabel(text.upper())
    label.setProperty("role", "section")
    return label


def status_row(name: str, state: str, value: str) -> QWidget:
    """One restrained status line, e.g. ``LOCAL AI  * NOT CONFIGURED``."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    dot = QLabel("●")
    dot.setProperty("state", state)

    value_label = QLabel(value.upper())
    value_label.setProperty("role", "mono")

    layout.addWidget(section_label(name))
    layout.addWidget(dot)
    layout.addWidget(value_label)
    layout.addStretch(1)
    return row


def horizontal_rule() -> QFrame:
    rule = QFrame()
    rule.setProperty("role", "rule")
    rule.setFrameShape(QFrame.Shape.NoFrame)
    rule.setFixedHeight(1)
    return rule


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(960, 640)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(6)

        wordmark = QLabel(APP_NAME.upper())
        wordmark.setProperty("role", "wordmark")

        descriptor = QLabel("PROJECT WORKSTATION")
        descriptor.setProperty("role", "descriptor")

        layout.addWidget(wordmark)
        layout.addWidget(descriptor)
        layout.addSpacing(24)
        layout.addWidget(horizontal_rule())
        layout.addStretch(1)

        layout.addWidget(horizontal_rule())
        layout.addSpacing(12)
        layout.addWidget(status_row("Local AI", "idle", "Not configured"))
        layout.addWidget(status_row("Cloud", "idle", "Off"))

        central.setLayout(layout)
        self.setCentralWidget(central)
        wordmark.setAlignment(Qt.AlignmentFlag.AlignLeft)
