"""The window behaves like a normal Mac application.

Not a brand concern, but a design one, and the kind of thing no test was watching: the
shell reported a minimum size of **88x88** because nothing had ever set one. Qt's
default is "as small as the layout claims it can go", and a ``QScrollArea`` claims it
can go to almost nothing -- so the Flight Deck happily shrank while the Workbench, which
has a real 811x444 of content, clipped its header instead.

What a normal window means here, and what each test pins:

* it opens at a comfortable working size rather than tiny or maximised;
* it can be resized down to a floor where the interface still works, and no further;
* it has no maximum, which is what lets macOS offer the green full-screen button;
* full screen and maximised both actually engage.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.agent.controller import AgentController  # noqa: E402
from opennest.agent.tools import Toolbox  # noqa: E402
from opennest.ai.provider import Reply  # noqa: E402
from tests.conftest import ScriptedProvider  # noqa: E402

#: Qt's "no limit" sentinel. A window that sets a real maximum cannot go full screen.
QWIDGETSIZE_MAX = 16_777_215


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from opennest.security import keychain
    from opennest.ui.main_window import MainWindow
    from tests.conftest import FakeKeyring

    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    monkeypatch.setattr("opennest.paths.projects_root", lambda: tmp_path / "projects")
    (tmp_path / "projects").mkdir(parents=True, exist_ok=True)
    shell = MainWindow("Elliot", credentials=keychain.Credentials(backend=FakeKeyring()))
    yield shell
    if shell._loader_thread is not None:
        shell._loader_thread.quit()
        shell._loader_thread.wait(5000)
    shell.close()


def test_it_opens_at_a_normal_working_size(window):
    """Big enough to work in, small enough to fit a 13-inch MacBook."""
    assert 1024 <= window.width() <= 1440
    assert 700 <= window.height() <= 900


def test_it_can_be_resized_down_but_not_into_nonsense(window):
    """The defect: no minimum at all, so the shell claimed it could be 88x88."""
    assert window.minimumWidth() >= 800, (
        f"the window can shrink to {window.minimumWidth()}px, where the Workbench "
        "header clips"
    )
    assert window.minimumHeight() >= 560
    # And the floor is a floor, not a second fixed size -- it must still fit a laptop.
    assert window.minimumWidth() <= 1024
    assert window.minimumHeight() <= 700


def test_the_floor_actually_clears_the_widest_screen(qt_app, project, window):
    """Measured against the Workbench rather than chosen and hoped for.

    The Flight Deck lives in a scroll area and has no meaningful minimum; the Workbench
    does, and its header is what drives it. If a future control makes that header wider
    than the window is allowed to be small, this says so instead of the header quietly
    clipping in a narrow window.
    """
    from opennest.ui.workbench import Workbench

    provider = ScriptedProvider([Reply(text="ok")])
    bench = Workbench(project, AgentController(project, provider, Toolbox(project)))
    try:
        needed = bench.layout().minimumSize()
        assert needed.width() <= window.minimumWidth(), (
            f"the Workbench needs {needed.width()}px but the window may shrink to "
            f"{window.minimumWidth()}px"
        )
        assert needed.height() <= window.minimumHeight()
    finally:
        bench.close()


def test_nothing_caps_the_size(window):
    """A maximum is what would remove the green full-screen button on macOS."""
    assert window.maximumWidth() >= QWIDGETSIZE_MAX
    assert window.maximumHeight() >= QWIDGETSIZE_MAX


def test_full_screen_and_maximised_both_engage(window):
    window.show()
    window.showFullScreen()
    assert window.isFullScreen()
    window.showNormal()
    assert not window.isFullScreen()
    window.showMaximized()
    assert window.isMaximized()
