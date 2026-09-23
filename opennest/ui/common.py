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


def mono_label(text: str, *, wrap: bool = False) -> QLabel:
    """File names, status, model information, timestamps.

    ``wrap`` is for the few places that show an absolute path. Without it such a label
    reports a size hint as wide as the path is long, and a monospace path is long: Phase
    10 measured the Local AI settings page asking for 1,021 px inside a 520 px scroll
    area because of one of these, which put a horizontal scrollbar on the page. Phase 9's
    smoke test had found the same defect on Parent Settings and measured it at 13 px
    (SPIKES.md 17F, defect 5), so this is the same fault in three places.

    It is opt-in rather than the default because most callers here are single-line status
    -- ``LOCAL AI  READY``, a timestamp, a model name -- where wrapping would let a row
    reflow into two lines instead of staying on one.
    """
    label = QLabel(text)
    label.setProperty("role", "mono")
    if wrap:
        label.setWordWrap(True)
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

    **"Behaves like a button" has to include the keyboard**, and until Phase 12 it did
    not. A QFrame's default focus policy is ``NoFocus``, so Tab never landed on one and
    Space and Return did nothing. Every card in the product is one of these -- the seven
    profile cards, the recent-project rows, and the starter and idea cards in New
    Project -- which left the Flight Deck's entire tab chain as
    ``QScrollArea -> Settings``. A child who cannot use a mouse could reach Parent
    Settings and nothing else: not a new project, not an existing one.

    Three things make it a button rather than a frame that can be focused: a focus
    policy, keyboard activation, and an accessible name, since a screen reader
    otherwise meets an unnamed frame containing two labels.
    """

    clicked = Signal()

    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # StrongFocus: reachable by Tab *and* by clicking, which is what a button does.
        # macOS only visits buttons with Full Keyboard Access on, and that is the user's
        # setting to make -- what matters here is that the application stops opting out.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._pressed = False

    def keyPressEvent(self, event) -> None:
        """Space and Return activate, the way they do on a real button.

        Both, deliberately: Space is the button convention, Return is what most people
        press, and a card is the one control on the Flight Deck worth reaching.
        """
        if event.key() in (
            Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter,
        ):
            event.accept()
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:
        self.setProperty("focused", True)
        self._restyle()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.setProperty("focused", False)
        self._restyle()
        super().focusOutEvent(event)

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
