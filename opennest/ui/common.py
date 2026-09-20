"""Small shared widgets that carry the Open Nest visual language.

Nothing here hard-codes a colour. Each widget sets a ``role`` or ``state`` property that
``opennest.ui.theme`` styles, so light and dark stay consistent for free.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


def section_label(text: str) -> QLabel:
    """An uppercase equipment-style header: PROJECT, ASSETS, LOCAL AI."""
    label = QLabel(text.upper())
    label.setProperty("role", "section")
    return label


def mono_label(text: str) -> QLabel:
    """File names, status, model information, timestamps."""
    label = QLabel(text)
    label.setProperty("role", "mono")
    return label


def horizontal_rule() -> QFrame:
    rule = QFrame()
    rule.setProperty("role", "rule")
    rule.setFrameShape(QFrame.Shape.NoFrame)
    rule.setFixedHeight(1)
    return rule


def status_row(name: str, state: str, value: str) -> QWidget:
    """One restrained status line, e.g. ``LOCAL AI  * READY``.

    DESIGN_DOC section 14: small, functional, never flashing or decorative.
    """
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


class ClickableFrame(QFrame):
    """A panel that behaves like a button.

    Not a QPushButton with a layout inside: QPushButton's size hint ignores child
    layouts, so such a "card" collapses and its labels never appear. A QFrame lays its
    children out correctly and still gives the bordered, rectangular, equipment-panel
    look DESIGN_DOC section 6 asks for.
    """

    clicked = Signal()

    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._pressed = False

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.setProperty("pressed", True)
            self._restyle()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.setProperty("pressed", False)
        self._restyle()
        if was_pressed and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event) -> None:
        self.setProperty("hovered", True)
        self._restyle()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hovered", False)
        self._pressed = False
        self._restyle()
        super().leaveEvent(event)

    def _restyle(self) -> None:
        """Qt does not re-evaluate property selectors on its own."""
        self.style().unpolish(self)
        self.style().polish(self)
