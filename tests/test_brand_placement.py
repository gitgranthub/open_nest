"""Where the brand artwork appears, and -- more importantly -- when it does not.

``tests/test_brand.py`` covers the component layer: sizes, contrast, registration,
HiDPI. This covers the wiring, and almost every test here is about *restraint* rather
than presence. Putting a mark on a screen is hard to get wrong and easy to see; the
failures that matter are the ones a screenshot cannot catch:

* an eagle that keeps flapping after the work finished, which turns "Open Nest is
  working" into decoration and makes it mean nothing (guide section 36);
* an approval mark on an ordinary event, which spends the one graphic the product has
  for a real milestone (section 39);
* a graphic with no text beside it, which is the accessibility rule in section 46;
* animation quietly replacing the numbers on a download, which section 53 forbids in
  as many words;
* a screen loading a brand PNG directly instead of going through the component layer,
  which is how sizing and dark-mode handling drift apart (section 45).

The developer's rule for the phase covers all of them: brand state must never imply a
technical state Open Nest has not actually established.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import Reply  # noqa: E402
from opennest.ui import brand  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

PACKAGE = Path(__file__).resolve().parent.parent / "opennest"


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def bench(qt_app, project):
    from opennest.ui.workbench import Workbench

    provider = ScriptedProvider([Reply(text="ok")] * 4)
    controller = AgentController(project, provider, Toolbox(project))
    widget = Workbench(project, controller)
    widget.resize(1180, 760)
    yield widget
    if widget._thread is not None:
        widget._thread.quit()
        widget._thread.wait(5000)
    widget.close()


def marks(widget) -> list:
    """Every brand graphic on a widget, found by pixmap rather than by object name."""
    from PySide6.QtWidgets import QLabel

    return [
        label for label in widget.findChildren(QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]


class _Run:
    """The parts of a ``RunResult`` the Workbench reads when showing one."""

    def __init__(self, ok=True, still_running=False):
        self.ok = ok
        self.still_running = still_running
        self.stdout = "output"
        self.failure_text = "" if ok else "boom"
        self.timed_out = False
        self.seconds = 0.1


class _Result:
    def __init__(self, run):
        self.run = run
        self.ok = run.ok
        self.content = ""


# --------------------------------------------------- nothing bypasses the component

def test_no_screen_loads_a_brand_asset_directly():
    """Guide section 45: no direct image-loading calls scattered through the app.

    ``brand.py`` is the only place that knows a prepared filename, which is what keeps
    sizing, dark-mode inversion, HiDPI and accessible naming consistent between screens.
    A screen that opened a PNG itself would look right today and drift the first time
    any of those four changed.
    """
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        if path.name == "brand.py":
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("open_nest_asset_delivery", "nest_w", "eagle_cycle", "glasses.png",
                       "open_nest_compact", "open_nest_wordmark", "approval_glasses"):
            if marker in text:
                offenders.append(f"{path.relative_to(PACKAGE)} mentions {marker!r}")
    assert not offenders, "brand assets must be reached through brand.py: " + "; ".join(offenders)


def test_every_placement_name_is_used_or_removed():
    """A placement nothing asks for is either dead or a screen that forgot to.

    Cheap to check and it catches the rename that leaves a screen falling back to a
    default size, which looks fine and is not what anybody approved.
    """
    used = set()
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in brand.PLACEMENTS:
            if f'"{name}"' in text:
                used.add(name)
    unused = set(brand.PLACEMENTS) - used
    assert not unused, f"placements defined but never used: {sorted(unused)}"


# --------------------------------------------------- the Flight Deck (section 56)

def test_the_flight_deck_carries_the_wordmark_and_the_nest(qt_app):
    """Section 56 makes this the strongest everyday expression of the brand."""
    from opennest.ui.flight_deck import FlightDeck

    deck = FlightDeck("Elliot")
    try:
        found = marks(deck)
        assert len(found) >= 2, "expected the wordmark and the nest"
        widths = sorted(m.pixmap().width() for m in found)
        assert widths[-1] >= 192, "the wordmark should be the hero element here"
    finally:
        deck.deleteLater()


def test_the_flight_deck_still_says_open_nest_in_text_somewhere(qt_app):
    """Section 30: the pixel wordmark is the brand mark, not the only way to say the name.

    Replacing the text masthead with artwork is right for the identity area and wrong if
    it leaves nothing for a screen reader or a person who cannot see the graphic. The
    accessible name on the mark is what carries it.
    """
    from opennest.ui.flight_deck import FlightDeck

    deck = FlightDeck("Elliot")
    try:
        names = [m.accessibleName() for m in marks(deck)]
        assert "Open Nest" in names
        # And exactly once: the nest beside it is the same identity, not a second one.
        assert names.count("Open Nest") == 1, (
            f"the identity is announced {names.count('Open Nest')} times: {names}"
        )
    finally:
        deck.deleteLater()


def test_the_eagle_flies_only_while_the_model_is_loading(qt_app):
    """Section 36: the eagle means work is happening, not that the app is running."""
    from opennest.ui.flight_deck import FlightDeck

    deck = FlightDeck("Elliot")
    try:
        assert not deck._eagle.running, "nothing is happening yet"
        assert deck._eagle.isHidden()

        deck.set_model_status("working", "Starting")
        assert deck._eagle.running
        assert not deck._eagle.isHidden()

        deck.set_model_status("ready", "Ready on this Mac")
        assert not deck._eagle.running, "the model answered; the bird must stop"
        assert deck._eagle.isHidden()
    finally:
        deck.deleteLater()


def test_a_failed_model_load_does_not_leave_the_eagle_flying(qt_app):
    """The case that would otherwise animate forever behind an error."""
    from opennest.ui.flight_deck import FlightDeck

    deck = FlightDeck("Elliot")
    try:
        deck.set_model_status("working", "Starting")
        deck.set_model_status("attention", "Not available")
        assert not deck._eagle.running
    finally:
        deck.deleteLater()


def test_updating_a_status_line_keeps_it_in_its_layout(qt_app):
    """A regression found by looking at the rendered window, not by any assertion.

    Putting the eagle beside the status lines moved them into a nested layout, and
    ``_replace_status`` was finding its layout with ``widget.parentWidget().layout()``.
    A nested layout adds no widget, so the page body was still the parent while the
    body's layout no longer contained the row: ``replaceWidget`` quietly did nothing,
    the replacement was never laid out, and it painted on top of the recent-projects
    list -- "Start with an idea" and "LOCAL AI CHECKING" rendered over each other.

    Nothing threw and every test passed. This pins the invariant the overlap violated:
    after an update there is exactly one row per status, and it is in the layout.
    """
    from opennest.ui.flight_deck import FlightDeck

    deck = FlightDeck("Elliot")
    try:
        lines = deck._status_lines
        before = lines.count()
        for _ in range(3):
            deck.set_model_status("ready", "Ready on this Mac")
            deck.set_cloud_status("ready", "On")
            deck.set_backup_status("ready", "Complete")
        assert lines.count() == before, "a status update added or lost a row"
        for row in (deck._status, deck._cloud_status, deck._backup_status):
            assert lines.indexOf(row) >= 0, "a live status row is not in the layout"
            assert row.parentWidget() is not None
    finally:
        deck.deleteLater()


def test_the_backup_row_says_only_what_a_child_may_see(qt_app):
    """The developer's split: state yes, queue depth and git vocabulary no."""
    from PySide6.QtWidgets import QLabel

    from opennest.ui.flight_deck import FlightDeck

    deck = FlightDeck("Elliot")
    try:
        deck.set_backup_status("working", "Waiting for internet")
        shown = " ".join(
            label.text() for label in deck._backup_status.findChildren(QLabel)
        ).lower()
        assert "backup" in shown
        assert "waiting for internet" in shown
        for forbidden in ("push", "commit", "repository", "branch", "queue", "git"):
            assert forbidden not in shown, f"{forbidden!r} is not the child's problem"
    finally:
        deck.deleteLater()


# --------------------------------------------------- the Workbench (section 57)

def test_the_workbench_header_carries_a_small_mark(bench):
    """Section 57: compact branding, and never a large area of the Workbench."""
    header = bench.layout().itemAt(0).layout()
    found = [
        header.itemAt(i).widget() for i in range(header.count())
        if header.itemAt(i).widget() is not None
        and header.itemAt(i).widget().property("role") is None
        and getattr(header.itemAt(i).widget(), "pixmap", None) is not None
        and header.itemAt(i).widget().pixmap() is not None
        and not header.itemAt(i).widget().pixmap().isNull()
    ]
    assert found, "no brand mark in the Workbench header"
    assert found[0].height() <= 96, "the header mark must stay small"


def test_the_dark_workbench_falls_back_to_the_nest(qt_app, project, monkeypatch):
    """The compact mark has no dark variant, and one cannot be built here.

    It is a pre-composited black ON over a white-ish nest, so inverting it blackens the
    nest, and rebuilding the lockup would be guessing at approved brand geometry.
    Section 48 permits the nest-only mark where the surrounding text already makes the
    product clear, and a header with the project name and "Workbench" does. This pins
    the fallback so a future dark compact variant is a deliberate swap rather than a
    surprise.
    """
    from opennest.ui import theme
    from opennest.ui.workbench import Workbench

    monkeypatch.setattr(theme, "is_dark", lambda *a, **k: True)
    provider = ScriptedProvider([Reply(text="ok")])
    widget = Workbench(project, AgentController(project, provider, Toolbox(project)))
    try:
        nest = brand.pixmap(brand.Mark.NEST, brand.PLACEMENTS["workbench_nest"][1])
        header_marks = [m for m in marks(widget) if m.pixmap().width() == nest.width()]
        assert header_marks, "dark mode should show the nest, not the compact lockup"
    finally:
        widget.close()


def test_the_eagle_runs_for_a_turn_and_stops(bench):
    """A turn is section 53's "meaningful wait", and it ends."""
    bench.working("Gary is working on it.")
    assert bench._eagle.running
    assert not bench._activity.isHidden()

    bench.working("")
    assert not bench._eagle.running
    assert bench._activity.isHidden()


def test_the_activity_indicator_is_never_shown_without_text(bench):
    """Section 46: a brand graphic is never the only signal.

    ``working()`` takes the status line rather than offering a bare start, so there is
    no way to produce a flapping bird with nothing next to it.
    """
    bench.working("")
    assert bench._activity.isHidden()
    bench.working("Making your picture.")
    assert bench._activity_text.text().strip()


def test_a_failed_turn_stops_the_eagle(bench):
    """Otherwise the bird outlives the thing it was reporting on."""
    bench.working("Gary is working on it.")
    bench._turn_failed("The local AI could not start.")
    assert not bench._eagle.running


# --------------------------------------------------- the approval mark (sections 38, 39)

def test_the_first_time_a_project_works_earns_the_mark(bench):
    """Section 38's "important project completion", on the one event that qualifies."""
    assert bench._completion.isHidden(), "nothing has run yet"
    bench._note_milestone()
    bench._show_run(_Result(_Run(ok=True)))
    assert not bench._completion.isHidden()
    assert bench._completion_text.text() == bench.FIRST_SUCCESS


def test_the_second_time_it_works_does_not(bench):
    """Section 39: not every successful run. Rarity is what makes it mean anything.

    Deliberately does **not** stamp the manifest between the two runs, which is what
    ``Toolbox._record_success`` would normally do. That save happens under
    ``contextlib.suppress(OSError)``, so a read-only or full disk produces exactly this
    sequence -- a success the manifest never recorded -- and the milestone must still
    not fire twice.
    """
    bench._note_milestone()
    bench._show_run(_Result(_Run(ok=True)))
    bench.completed("")

    bench._note_milestone()
    bench._show_run(_Result(_Run(ok=True)))
    assert bench._completion.isHidden(), "the mark fired twice for the same project"


def test_a_failed_run_earns_nothing(bench):
    bench._note_milestone()
    bench._show_run(_Result(_Run(ok=False)))
    assert bench._completion.isHidden()


def test_reopening_a_project_that_already_works_shows_nothing(qt_app, project):
    """Once per project, not once per session -- the manifest is what remembers."""
    from opennest.ui.workbench import Workbench

    project.manifest.last_successful_run = "2026-01-01T00:00:00+00:00"
    provider = ScriptedProvider([Reply(text="ok")])
    widget = Workbench(project, AgentController(project, provider, Toolbox(project)))
    try:
        assert widget._worked_before
        widget._note_milestone()
        widget._show_run(_Result(_Run(ok=True)))
        assert widget._completion.isHidden()
    finally:
        widget.close()


def test_the_approval_line_claims_nothing_the_run_did_not_show(bench):
    """``RunResult.ok`` means different things per profile, and the copy must survive all.

    For a batch project it means the program ran to completion; for a compile it means
    the compiler accepted the sketch; for an interactive game it means only that the
    process survived a four-second startup grace and is on screen. "It works." would be
    an unverified claim in that last case, which is exactly what the phase's rule about
    brand state forbids. "You built that." is about authorship and is true in all three.
    """
    claim = bench.FIRST_SUCCESS.lower()
    for forbidden in ("works", "working", "runs", "playable", "finished", "fixed"):
        assert forbidden not in claim, (
            f"{bench.FIRST_SUCCESS!r} asserts {forbidden!r}, which one successful run "
            "does not establish for every profile"
        )


# --------------------------------------------------- the setup wizard (section 58)

def test_the_download_keeps_its_numbers_when_the_eagle_appears():
    """Section 53: "never replace useful numerical progress information with animation".

    Read from the source rather than by driving a real download: a 2.3 GB fetch is not
    something a test starts, and what matters is that the progress bar and the byte
    counts are still written alongside the indicator rather than swapped for it.
    """
    source = (PACKAGE / "setup" / "wizard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    progress = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_on_progress"
    )
    body = ast.unparse(progress)
    assert "_bar.setValue" in body, "the percentage must still be reported"
    assert "describe()" in body, "the real byte counts must still be reported"


def test_the_wizard_opens_with_the_identity_and_ends_with_the_approval_mark(qt_app, tmp_path,
                                                                           monkeypatch):
    """Section 58's sequence, which is what teaches the visual language."""
    from opennest.security import keychain, permissions
    from opennest.setup.state import InstallationState
    from opennest.setup.wizard import FinishStep, SetupWizard, WelcomeStep

    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    from tests.conftest import FakeKeyring

    wizard = SetupWizard(
        state=InstallationState(path=tmp_path / "installation.json"),
        controls=permissions.ParentControls(path=tmp_path / "settings.json"),
        credentials=keychain.Credentials(backend=FakeKeyring()),
    )
    try:
        welcome = next(s for s in wizard.steps if isinstance(s, WelcomeStep))
        finish = next(s for s in wizard.steps if isinstance(s, FinishStep))
        assert marks(welcome), "the wizard should open with the Open Nest identity"
        assert marks(finish), "setup finishing is the clearest case for the approval mark"
        # And the graphic is not the only signal (section 46).
        from PySide6.QtWidgets import QLabel

        said = " ".join(label.text() for label in finish.findChildren(QLabel))
        assert "ready" in said.lower()
    finally:
        wizard.deleteLater()
