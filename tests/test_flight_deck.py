"""Flight Deck behaviour that is logic rather than appearance.

Same reasoning as ``tests/test_workbench.py``: nothing here asserts on pixels, and what
it does assert is the part that regresses silently. The project list is that part --
Phase 12 found it showing the six most recent with nothing after them, so a seventh
project was on disk and unreachable from the interface.

Runs under ``offscreen``; ``qt_app`` comes from tests/conftest.py.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _deck(qt_app):
    from opennest.ui.flight_deck import FlightDeck

    return FlightDeck("Elliot", allow_cloud=False, credentials=None)


def _settle(qt_app) -> None:
    """Let deferred deletions actually happen.

    ``refresh`` clears the list with ``deleteLater``, which does nothing until the
    event loop turns. Without this, ``findChildren`` counts the old rows as well as
    the new ones and a test reads 15 where it means 9.
    """
    from PySide6.QtCore import QEvent

    qt_app.processEvents()
    qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _rows(deck):
    from opennest.ui.flight_deck import RecentProjectRow

    return deck.findChildren(RecentProjectRow)


def _more_row(deck):
    from opennest.ui.flight_deck import MoreProjectsRow

    rows = deck.findChildren(MoreProjectsRow)
    return rows[0] if rows else None


def test_a_seventh_project_is_reachable(qt_app, tmp_path, monkeypatch) -> None:
    """The defect: ``list_projects()[:6]`` with nothing offering the rest.

    A child who makes seven games could not open the first one from the interface at
    all -- the files were there, the manifest was there, and no screen would show it.
    """
    from opennest.projects.manager import create_project
    from opennest.ui import flight_deck

    made = [create_project(f"Game {n}", "games", root=tmp_path) for n in range(9)]
    monkeypatch.setattr(flight_deck, "list_projects", lambda: made)

    deck = _deck(qt_app)
    try:
        _settle(qt_app)
        assert len(_rows(deck)) == flight_deck.RECENT_SHOWN
        more = _more_row(deck)
        assert more is not None, "nine projects, six shown, and no way to the other three"
        assert "9" in more.accessibleName(), more.accessibleName()

        more.clicked.emit()
        _settle(qt_app)
        assert len(_rows(deck)) == 9, "expanding did not show every project"

        fewer = _more_row(deck)
        assert fewer is not None and "fewer" in fewer.accessibleName().lower()
        fewer.clicked.emit()
        _settle(qt_app)
        assert len(_rows(deck)) == flight_deck.RECENT_SHOWN
    finally:
        deck.deleteLater()


def test_a_short_list_is_not_given_a_control_it_does_not_need(
    qt_app, tmp_path, monkeypatch
) -> None:
    from opennest.projects.manager import create_project
    from opennest.ui import flight_deck

    made = [create_project(f"Game {n}", "games", root=tmp_path) for n in range(3)]
    monkeypatch.setattr(flight_deck, "list_projects", lambda: made)

    deck = _deck(qt_app)
    try:
        _settle(qt_app)
        assert len(_rows(deck)) == 3
        assert _more_row(deck) is None
    finally:
        deck.deleteLater()


def test_the_way_to_the_rest_is_reachable_without_a_mouse(
    qt_app, tmp_path, monkeypatch
) -> None:
    """It is a row like the projects above it, so it inherits their keyboard behaviour."""
    from PySide6.QtCore import Qt

    from opennest.projects.manager import create_project
    from opennest.ui import flight_deck

    made = [create_project(f"Game {n}", "games", root=tmp_path) for n in range(8)]
    monkeypatch.setattr(flight_deck, "list_projects", lambda: made)

    deck = _deck(qt_app)
    try:
        more = _more_row(deck)
        assert more.focusPolicy() != Qt.FocusPolicy.NoFocus
        assert more.accessibleName()
    finally:
        deck.deleteLater()
