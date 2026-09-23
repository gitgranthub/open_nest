"""About Gary -- a small aside for anyone who wonders who Gary is.

The interface now calls the assistant Gary by name, so someone will eventually wonder.
This answers that, and nothing more. It is **not** onboarding, a character profile, or
lore: it appears only when a person clicks the quiet glyph beside his name, and there is
no path by which it opens on its own.

Three constraints shape it, and each is the brand guide rather than taste:

* **No face, and no borrowed artwork.** Guide section 47 keeps Gary and the pixel
  symbols apart -- the eagle, nest and sunglasses belong to Open Nest. So there is no
  illustration here, no avatar, and the bio never mentions them.
  ``test_gary_never_names_the_brand_artwork`` sweeps this file along with every other.
* **Dry.** Section 1 and section 21 both rule out performed personality; section 18
  rules out manufactured enthusiasm. The humour is in the third person and in the last
  line, not in exclamation marks. No emoji.
* **A popover, not a dialog.** A modal window would make reading a joke feel like a
  task. ``Qt.Popup`` dismisses on the next click anywhere, which is the behaviour a
  person expects from an information glyph.

The last line is the whole joke and is load-bearing: the bio is written throughout in
the third person and then signs itself. Do not "fix" it into the first person, and do
not delete it -- ``test_gary_wrote_his_own_bio`` exists because it reads like a stray
sentence to anyone who has not been told.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

#: U+24D8. A typographic glyph rather than an emoji, which section 41 rules out.
GLYPH = "ⓘ"

TITLE = "About Gary"

#: The long form, which is the approved one wherever it fits. ``POPOVER_WIDTH`` is set
#: so that it does.
BIO = (
    "Gary is the helpful Open Nest assistant.\n\n"
    "Gary likes clear plans, unusual ideas, performance art, and expressive dance. He "
    "has strong opinions about unnecessary complexity and occasionally about variable "
    "names.\n\n"
    "Gary believes most things can be improved with patience, commitment, and, in "
    "specific circumstances, movement.\n\n"
    "Gary wrote this bio."
)

#: The approved short form, for somewhere genuinely cramped. Nothing uses it yet; it is
#: here so that a future placement shortens the bio by choosing this rather than by
#: inventing a third version and losing the last line.
SHORT_BIO = (
    "Gary is the helpful Open Nest assistant. He likes unusual ideas, performance art, "
    "expressive dance, and projects that eventually work. He has opinions about "
    "unnecessary complexity.\n\n"
    "Gary wrote this bio."
)

#: Wide enough for the long bio to read as a few short paragraphs rather than a column.
POPOVER_WIDTH = 320


class AboutPopover(QFrame):
    """A small floating card. Dismissed by clicking anywhere, like any popover.

    ``Qt.Popup`` is what makes that true: Qt grabs the mouse and closes the window on
    the next click outside it, with no button to press and nothing to block the
    interface behind it.
    """

    def __init__(self, parent: QWidget | None = None, *, text: str = BIO) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setProperty("role", "popover")
        self.setFixedWidth(POPOVER_WIDTH)

        margins = (14, 12, 14, 14)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*margins)
        layout.setSpacing(8)

        heading = QLabel(TITLE)
        heading.setProperty("role", "cardTitle")
        self.body = QLabel(text)
        self.body.setProperty("role", "cardBody")
        self.body.setWordWrap(True)
        # Fixed to the content width, and this is load-bearing rather than tidiness. A
        # wrapped QLabel reports a one-line ``sizeHint`` until something constrains its
        # width, so ``adjustSize`` on the popover computed a height for a single line
        # and clipped the bio -- losing the last paragraph, which is the whole point of
        # it. Constraining the label first makes its hint the real wrapped height.
        self.body.setFixedWidth(POPOVER_WIDTH - margins[0] - margins[2])
        layout.addWidget(heading)
        layout.addWidget(self.body)


def show_about(anchor: QWidget, *, text: str = BIO) -> AboutPopover:
    """Open the popover just below ``anchor``, kept on screen."""
    popover = AboutPopover(anchor, text=text)
    popover.adjustSize()

    where = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
    screen = anchor.screen()
    if screen is not None:
        # A glyph near the right edge of the window would otherwise open a popover
        # half off the display.
        available = screen.availableGeometry()
        x = min(where.x(), available.right() - popover.width() - 8)
        y = min(where.y(), available.bottom() - popover.height() - 8)
        where = QPoint(max(available.left() + 8, x), max(available.top() + 8, y))

    popover.move(where)
    popover.show()
    return popover


def info_button(text: str = BIO) -> QPushButton:
    """The quiet glyph that sits beside Gary's name.

    A ``QPushButton`` rather than a ``QToolButton`` because the theme styles the former
    and not the latter, and ``role="info"`` strips it back to a borderless character so
    it reads as a hint rather than as a control competing with Send.
    """
    button = QPushButton(GLYPH)
    button.setProperty("role", "info")
    # Guide section 46: an affordance carrying no text needs an ordinary accessible
    # name. "About Gary" is what it does, said plainly.
    button.setAccessibleName(TITLE)
    button.setToolTip(TITLE)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFlat(True)
    button.clicked.connect(lambda: show_about(button, text=text))
    return button
