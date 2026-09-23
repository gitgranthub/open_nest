"""Design tokens and stylesheet for Open Nest.

Implements DESIGN_DOC.md: a clean modern reading of a late-1980s / early-1990s creative
workstation. Retro-informed, not retro-simulated -- the character comes from proportion,
restrained colour, equipment-style labelling and control shapes, never from decorative
nostalgia effects.

Widgets should never hard-code a colour. Use these tokens, or a ``role`` property that
the stylesheet below knows about:

    label.setProperty("role", "section")    # PROJECT, ASSETS, LOCAL AI
    label.setProperty("role", "mono")       # file names, status, model info, timestamps
    dot.setProperty("state", "ready")       # ready | working | idle | attention
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

#: Restrained monospace for technical information only (DESIGN_DOC.md section 5).
#:
#: Menlo first because it is the macOS default monospace and is always present. SF Mono
#: is deliberately absent: macOS ships it inside Terminal.app rather than registering it
#: as a system family, so naming it here only costs a font-alias scan at startup before
#: Qt falls back to Menlo anyway.
MONO_FAMILY = '"Menlo", "Monaco", monospace'

#: Modest corner radius. Rectangular controls with visible borders, not pills.
RADIUS_PX = 3


@dataclass(frozen=True)
class Palette:
    """One complete colour scheme. Warm neutrals, few and muted accents."""

    window: str
    surface: str
    surface_alt: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    control: str
    control_hover: str
    control_pressed: str
    accent: str
    accent_text: str
    ok: str
    info: str
    attention: str


#: Warm beige / bone, soft off-white, charcoal, graphite, warm gray.
LIGHT = Palette(
    window="#E7E2D8",
    surface="#F2EFE8",
    surface_alt="#FAF8F3",
    border="#C8C1B2",
    border_strong="#A79E8D",
    text="#2B2825",
    text_muted="#6C6559",
    control="#EDE9E1",
    control_hover="#E4DFD5",
    control_pressed="#D6D0C3",
    accent="#B96A16",
    accent_text="#FFFFFF",
    ok="#5C8A4C",
    info="#4C6479",
    attention="#9A4B33",
)

#: "The room lights were lowered", not "the software became futuristic".
DARK = Palette(
    window="#1E1C1A",
    surface="#272420",
    surface_alt="#302D28",
    border="#433F38",
    border_strong="#59544B",
    text="#EDE7DC",
    text_muted="#9B9486",
    control="#302D28",
    control_hover="#3A362F",
    control_pressed="#24211D",
    accent="#D08B3C",
    accent_text="#1E1C1A",
    ok="#7CA468",
    info="#7690A6",
    attention="#C06A50",
)


def resolve_palette(app: QApplication | None = None) -> Palette:
    """Pick the palette matching the system appearance."""
    hints = (app or QGuiApplication.instance()).styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None and scheme() == Qt.ColorScheme.Dark:
        return DARK
    return LIGHT


def is_dark(app: QApplication | None = None) -> bool:
    """Whether the dark palette is in force.

    Screens need this because the brand marks are not all legible on both surfaces:
    three of them have to be inverted for a charcoal background and two have to be left
    alone, and :mod:`opennest.ui.brand` decides which from a ``dark`` flag. This is the
    one place that flag comes from, so a widget never reads a colour to infer a scheme.
    """
    return resolve_palette(app) is DARK


def stylesheet(palette: Palette) -> str:
    """Build the application stylesheet for a palette."""
    return _TEMPLATE.format(p=palette, radius=RADIUS_PX, mono=MONO_FAMILY)


def apply(app: QApplication, palette: Palette | None = None) -> None:
    """Apply the theme, and keep following the system appearance if Qt reports changes."""
    app.setStyleSheet(stylesheet(palette or resolve_palette(app)))

    hints = app.styleHints()
    changed = getattr(hints, "colorSchemeChanged", None)
    if palette is None and changed is not None:
        changed.connect(lambda _scheme: app.setStyleSheet(stylesheet(resolve_palette(app))))


_TEMPLATE = """
QWidget {{
    background-color: {p.window};
    color: {p.text};
}}

QMainWindow, QDialog {{
    background-color: {p.window};
}}

QLabel {{
    background: transparent;
}}

/* Equipment-style section headers: PROJECT, ASSETS, LOCAL AI, STATUS, BUILD. */
QLabel[role="section"] {{
    color: {p.text_muted};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.5px;
}}

QLabel[role="greeting"] {{
    color: {p.text};
    font-size: 19px;
}}

QLabel[role="question"] {{
    color: {p.text_muted};
    font-size: 15px;
}}

QLabel[role="projectTitle"] {{
    color: {p.text};
    font-size: 15px;
    font-weight: 600;
}}

QLabel[role="cardTitle"] {{
    color: {p.text};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.6px;
}}

QLabel[role="cardBody"] {{
    color: {p.text_muted};
    font-size: 12px;
}}

/* Choices on the Flight Deck. Rectangular with a visible border, left-aligned --
   equipment panels, not floating cards. */
QFrame#profileCard, QFrame#recentRow {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius}px;
}}

QFrame#profileCard[hovered="true"], QFrame#recentRow[hovered="true"] {{
    background-color: {p.surface_alt};
    border-color: {p.border_strong};
}}

QFrame#profileCard[pressed="true"], QFrame#recentRow[pressed="true"] {{
    background-color: {p.control_pressed};
    border-color: {p.text_muted};
}}

/* The card a child has actually picked, in the one place a card is a choice rather
   than a doorway: how a new project starts (opennest/ui/new_project.py). Border and
   weight only -- section 25 keeps the accent for activity and approval, and a selected
   row is neither. */
QFrame#profileCard[state="chosen"] {{
    border: 2px solid {p.text};
    background-color: {p.surface_alt};
}}

QFrame#profileCard[state="unchosen"] {{
    border: 1px solid {p.border};
}}

QSplitter::handle {{
    background-color: {p.border};
}}

QLabel[role="descriptor"] {{
    color: {p.text_muted};
    font-size: 10px;
    letter-spacing: 3px;
}}

/* File names, status labels, model information, build output, code, timestamps. */
QLabel[role="mono"], QPlainTextEdit[role="mono"], QTextEdit[role="mono"] {{
    font-family: {mono};
    font-size: 11px;
    color: {p.text_muted};
}}

/* A code a person reads off the screen and types somewhere else -- the GitHub device
   flow's user code. This is the focal element of its dialog, so unlike role="mono" it
   is scaled up and in the full text colour rather than the muted one. Phase 9's smoke
   test found the device code rendered at mono's 11px and muted grey, which made the one
   thing a parent had to read the quietest thing on screen (SPIKES.md 17F, defect 3). */
QLabel[role="deviceCode"] {{
    font-family: {mono};
    font-size: 28px;
    font-weight: 600;
    letter-spacing: 4px;
    color: {p.text};
    background-color: {p.surface_alt};
    border: 1px solid {p.border_strong};
    border-radius: {radius}px;
    padding: 10px 16px;
}}

/* Small, functional status indicators. Never flashing or decorative. */
QLabel[state="ready"] {{ color: {p.ok}; }}
QLabel[state="working"] {{ color: {p.accent}; }}
QLabel[state="idle"] {{ color: {p.text_muted}; }}
QLabel[state="attention"] {{ color: {p.attention}; }}

QFrame[role="panel"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius}px;
}}

QFrame[role="rule"] {{
    background-color: {p.border};
    border: none;
    max-height: 1px;
}}

/* A bare container that must not paint over the panel behind it. Qt gives every
   QWidget the window colour, so a plain layout holder dropped inside a panel draws a
   window-coloured band across it -- visible under the wizard's and the Workbench's
   activity rows before this existed. QLabel already gets the same treatment above. */
QWidget[role="bare"] {{
    background: transparent;
}}

/* Progress. Left unstyled until Phase 10C, which meant the one place a parent watches
   for two hundred seconds -- the model download -- rendered macOS's system blue in the
   middle of a warm bone-and-charcoal page. Section 25 names restrained amber as the
   accent for exactly this ("loading progress"), and section 41 lists conflicting
   chrome as something to avoid. Think indicator lamp, not consumer app. */
QProgressBar {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border_strong};
    border-radius: {radius}px;
    max-height: 10px;
    text-align: center;
    color: {p.text};
}}

QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: {radius}px;
}}

/* Rectangular, modest radius, visible border, obvious pressed and disabled states. */
QPushButton {{
    background-color: {p.control};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {radius}px;
    padding: 6px 14px;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {p.control_hover};
}}

QPushButton:pressed {{
    background-color: {p.control_pressed};
    border-color: {p.text_muted};
}}

QPushButton:disabled {{
    color: {p.text_muted};
    border-color: {p.border};
    background-color: {p.surface};
}}

QPushButton[role="primary"] {{
    background-color: {p.accent};
    color: {p.accent_text};
    border-color: {p.accent};
    font-weight: 600;
}}

QPushButton[role="primary"]:hover {{
    background-color: {p.accent};
}}

QPushButton[role="primary"]:disabled {{
    background-color: {p.control};
    color: {p.text_muted};
    border-color: {p.border};
}}

/* A quiet "tell me more" glyph. Borderless and muted so it reads as a hint beside a
   section label rather than as a control competing with the panel's real buttons --
   it should be findable by someone curious and invisible to everyone else. */
QPushButton[role="info"] {{
    background: transparent;
    border: none;
    color: {p.text_muted};
    padding: 0px 2px;
    min-height: 0px;
    font-size: 13px;
}}

QPushButton[role="info"]:hover {{
    background: transparent;
    color: {p.text};
}}

/* A small floating card. Stronger border than a panel because it sits *over* the
   interface rather than inside it, and there is no drop shadow doing that job --
   section 28 rules out adding one merely to modernise. */
QFrame[role="popover"] {{
    background-color: {p.surface_alt};
    border: 1px solid {p.border_strong};
    border-radius: {radius}px;
}}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {radius}px;
    padding: 5px 8px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {p.accent};
}}

QListView, QTreeView {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: {radius}px;
    outline: none;
}}

QListView::item:selected, QTreeView::item:selected {{
    background-color: {p.control_pressed};
    color: {p.text};
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    width: 10px;
    height: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QToolTip {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border_strong};
    padding: 4px 6px;
}}
"""
