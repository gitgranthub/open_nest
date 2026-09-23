"""The interface can be used without a mouse.

Phase 12 pressed Tab for the first time. On the Flight Deck the whole chain was
``QScrollArea -> Settings``: seven profile cards, the recent-project rows, and the
starter and idea cards in New Project were all ``QFrame`` subclasses at the default
``NoFocus``, so a keyboard user could reach Parent Settings and nothing else. Not a new
project, not an existing one. The screen's own question -- "What do you want to make?" --
had no keyboard answer.

Nothing here asserts on pixels. Whether the focus ring is *visible* stays a look, and
`spikes/phase12/keyboard.py` is what renders it; what this file pins is that the
keyboard can reach and operate every primary action.

Runs under ``offscreen``. Focus policy and key handling are properties of the widgets,
not of the window server, so they are testable without a display -- but note that macOS
only *visits* non-text controls with Full Keyboard Access on, which is the user's
setting. What the application controls is whether it opts out, and that is what this
checks.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ``qt_app`` and ``wizard`` come from tests/conftest.py.


def _keyboard_reaches(widget) -> bool:
    from PySide6.QtCore import Qt

    return widget.focusPolicy() != Qt.FocusPolicy.NoFocus


def _activates(widget, key) -> bool:
    """Press a key on the widget and report whether ``clicked`` fired."""
    from PySide6.QtTest import QTest

    fired: list = []
    widget.clicked.connect(lambda: fired.append(True))
    QTest.keyClick(widget, key)
    return bool(fired)


# --------------------------------------------------------------- the cards

def test_a_clickable_card_is_reachable_and_operable_from_the_keyboard(qt_app) -> None:
    from PySide6.QtCore import Qt

    from opennest.ui.common import ClickableFrame

    card = ClickableFrame("profileCard")
    assert _keyboard_reaches(card), "Tab cannot land on a card"
    assert _activates(card, Qt.Key.Key_Space), "Space does nothing on a card"
    assert _activates(card, Qt.Key.Key_Return), "Return does nothing on a card"
    assert _activates(card, Qt.Key.Key_Enter), "the numeric Enter does nothing"


def test_an_unrelated_key_does_not_activate_a_card(qt_app) -> None:
    """Otherwise typing anywhere near one starts a project."""
    from PySide6.QtCore import Qt

    from opennest.ui.common import ClickableFrame

    card = ClickableFrame("profileCard")
    assert not _activates(card, Qt.Key.Key_A)
    assert not _activates(card, Qt.Key.Key_Tab)


def test_every_profile_on_the_flight_deck_can_be_chosen_without_a_mouse(qt_app) -> None:
    from PySide6.QtCore import Qt

    from opennest.ui.flight_deck import FlightDeck, ProfileCard

    deck = FlightDeck("Elliot", allow_cloud=False, credentials=None)
    cards = deck.findChildren(ProfileCard)
    assert cards, "no profile cards to check"

    unreachable = [c.profile.id for c in cards if not _keyboard_reaches(c)]
    assert not unreachable, f"mouse-only profiles: {unreachable}"

    chosen: list = []
    enabled = [c for c in cards if c.isEnabled()]
    enabled[0].clicked.connect(lambda: chosen.append(True))
    from PySide6.QtTest import QTest

    QTest.keyClick(enabled[0], Qt.Key.Key_Return)
    assert chosen, "Return on a profile card started nothing"
    deck.deleteLater()


def test_a_card_says_what_it_is_to_a_screen_reader(qt_app) -> None:
    """A frame holding two labels is announced as neither."""
    from opennest.ui.flight_deck import FlightDeck, ProfileCard

    deck = FlightDeck("Elliot", allow_cloud=False, credentials=None)
    for card in deck.findChildren(ProfileCard):
        assert card.accessibleName(), f"{card.profile.id} has no accessible name"
        assert card.accessibleName() == card.profile.name
    deck.deleteLater()


def test_starter_and_idea_cards_are_reachable_too(qt_app) -> None:
    """The New Project dialog is the other place a card is the only way through."""
    from opennest.projects.profiles import load_profiles
    from opennest.ui.new_project import IdeaCard, NewProjectDialog, StarterCard

    games = next(p for p in load_profiles() if p.id == "games")
    dialog = NewProjectDialog(None, games)

    cards = dialog.findChildren(StarterCard) + dialog.findChildren(IdeaCard)
    assert cards, "the Games dialog offered neither a starter nor an idea"
    assert all(_keyboard_reaches(card) for card in cards)
    assert all(card.accessibleName() for card in cards)
    dialog.deleteLater()


# --------------------------------------------------------------- the wizard

def test_return_means_continue_in_the_setup_wizard(wizard) -> None:
    """Qt picks a default button when a dialog does not, and it picked badly.

    With nothing declared, ``isDefault`` landed on "Show other options" -- a control on
    the Local AI step, invisible from every other page. So Return did nothing on eight
    of the nine steps and would have toggled a fold-out on the ninth.
    """
    from PySide6.QtWidgets import QPushButton

    defaults = [b.text() for b in wizard.findChildren(QPushButton) if b.isDefault()]
    assert defaults == [wizard._next.text()], (
        f"the default button is {defaults}, not the footer's primary action"
    )


def test_the_default_button_follows_the_step(wizard) -> None:
    """The label changes per step; the default must stay the same control."""
    from PySide6.QtWidgets import QPushButton

    for index in (0, 1, len(wizard.steps) - 1):
        wizard._show_step(index)
        defaults = [b for b in wizard.findChildren(QPushButton) if b.isDefault()]
        assert defaults == [wizard._next], f"step {index + 1} lost its default button"


def test_the_step_that_needs_typing_gets_the_cursor(wizard) -> None:
    """Arriving at "Who will use Open Nest?" used to focus the page's scroll area."""
    wizard._show_step(1)
    step = wizard.steps[1]
    assert step.initial_focus() is step._name
    assert step._name.hasFocus() or wizard.focusWidget() is step._name


def test_escape_does_not_throw_away_a_half_finished_setup(wizard) -> None:
    """A QDialog rejects on Escape, and rejecting here discards everything.

    ``installation.json`` is written once, at the end, so the child's name, the Git
    identity, the verified model, the cloud choice and the GitHub account all live on
    ``state`` until then. Escape dropped the lot with no prompt and left
    ``setup_complete`` false, so the next launch started again at step 1.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    rejected: list = []
    wizard.rejected.connect(lambda: rejected.append(True))
    wizard._show_step(1)
    QTest.keyClick(wizard, Qt.Key.Key_Escape)
    assert not rejected, "Escape ended setup"


def test_quit_setup_is_still_immediate(wizard) -> None:
    """Escape is the accident; the button is a decision, and it keeps working."""
    from PySide6.QtWidgets import QPushButton

    rejected: list = []
    wizard.rejected.connect(lambda: rejected.append(True))
    quit_button = next(
        b for b in wizard.findChildren(QPushButton) if b.text() == "Quit Setup"
    )
    quit_button.click()
    assert rejected
