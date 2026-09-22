"""The five cosmetic defects Phase 9's UI smoke test found, pinned so they stay fixed.

SPIKES.md 17F recorded them after driving the real controls under the **cocoa** platform
and looking at the result. None affected behaviour, which is exactly why no existing test
caught any of them: every one is a fact about geometry or emphasis, and the suite's rule
is that Qt tests assert decisions rather than pixels.

These are the exception, and deliberately so. A clipped label, a duplicated code, a
control 726 px down a 443 px viewport and a page wider than its own scroll area are all
*measurable* -- they are not matters of taste, and each has a number attached. So these
tests assert on size hints and layout positions rather than on appearance, and none of
them looks at a colour or a font face.

**These run offscreen, and offscreen is not cocoa.** Font metrics differ, so the absolute
numbers here are not the ones in SPIKES.md -- the GitHub block measured 726 px down a
443 px viewport under cocoa and 676 px down a 431 px one here. The defects reproduce
identically under both; the thresholds below are set with enough margin to survive the
difference, and a final look under cocoa stays on the manual checklist.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.github import auth  # noqa: E402
from opennest.github.transport import Response  # noqa: E402
from opennest.security import keychain, permissions  # noqa: E402
from tests.conftest import FakeKeyring  # noqa: E402

CODE_URL_SUFFIX = "/login/device/code"


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    from opennest.ui import theme

    app = QApplication.instance() or QApplication([])
    theme.apply(app, theme.LIGHT)
    return app


class _CodeTransport:
    """Answers only the device-code call, which is all these tests reach."""

    def __init__(self, user_code: str = "WDJB-MJHT") -> None:
        self.user_code = user_code

    def request(self, method, url, *, headers=None, body=None):
        if method == "POST" and url.endswith(CODE_URL_SUFFIX):
            return Response(200, {
                "user_code": self.user_code,
                "device_code": "secret-device-code-half",
                "verification_uri": "https://github.com/login/device",
                "interval": 5,
                "expires_in": 900,
            })
        return Response(404, {"message": "Not Found"})


@pytest.fixture
def settings_window(qt_app, tmp_path, monkeypatch):
    from opennest.ui.settings import SettingsWindow

    monkeypatch.setattr(auth, "CLIENT_ID", "Iv1.test0client0id")
    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    window = SettingsWindow(
        controls=permissions.ParentControls(path=tmp_path / "settings.json"),
        credentials=keychain.Credentials(backend=FakeKeyring()),
    )
    window.resize(720, 520)
    window.show()
    qt_app.processEvents()
    window._unlocked = True
    yield window
    window.deleteLater()


def _page_and_viewport(window, name):
    from opennest.ui.settings import PAGES

    row = PAGES.index(name)
    window._nav.setCurrentRow(row)
    for _ in range(4):
        window.parent() if False else None
        from PySide6.QtWidgets import QApplication

        QApplication.instance().processEvents()
    area = window._stack.widget(row)
    return area.widget(), area.viewport(), area


def _label_y(page, text):
    from PySide6.QtWidgets import QLabel

    for child in page.findChildren(QLabel):
        if child.text().strip().upper() == text.upper():
            return child.mapTo(page, child.rect().topLeft()).y()
    raise AssertionError(f"no label reading {text!r} on the page")


# --------------------------------------------- defect 4: GitHub Backup was buried

def test_github_backup_is_visible_without_scrolling(settings_window):
    """WORKORDER_01 section 29A presents this as a headline parent control.

    Measured before the fix: 726 px down a 443 px viewport in 1,230 px of content under
    cocoa, so a parent scrolled roughly 63% of the page to find it.
    """
    page, viewport, _ = _page_and_viewport(settings_window, "Parent Settings")
    y = _label_y(page, "GitHub Backup")
    assert y < viewport.height(), (
        f"GitHub Backup sits {y}px down a {viewport.height()}px viewport -- "
        "a parent has to scroll to reach a headline control"
    )


def test_moving_github_backup_up_did_not_push_cloud_ai_out_of_sight(settings_window):
    """The fix must not simply move the problem onto the next control.

    Cloud AI is the safety-critical switch on this page, so it stays above the fold too.
    """
    page, viewport, _ = _page_and_viewport(settings_window, "Parent Settings")
    y = _label_y(page, "Cloud AI")
    assert y < viewport.height(), (
        f"Cloud AI now sits {y}px down a {viewport.height()}px viewport"
    )


# --------------------------------------------- defect 5: a horizontal scrollbar

@pytest.mark.parametrize(
    "name",
    ["General", "Local AI", "Cloud AI", "Parent Settings", "Projects", "Advanced"],
)
def test_no_settings_page_is_wider_than_its_own_scroll_area(settings_window, name):
    """Measured before the fix: the Parent Settings page needed 523 px in a 510 px
    viewport -- exactly the 13 px of horizontal scroll Qt reported.

    The cause was ``_key_row`` packing five fixed-width widgets into one row that could
    not compress: ``Anthropic`` 66 + ``Not configured`` 93 + ``Add API Key`` 102 +
    ``Test Connection`` 125 + ``Remove`` 77, plus 4 x 6 px spacing. Every page is checked
    rather than just that one, because the next wide row would be just as invisible.
    """
    page, viewport, area = _page_and_viewport(settings_window, name)
    needed = page.minimumSizeHint().width()
    assert needed <= viewport.width(), (
        f"the {name} page needs {needed}px in a {viewport.width()}px viewport"
    )
    assert area.horizontalScrollBar().maximum() == 0, (
        f"the {name} page has {area.horizontalScrollBar().maximum()}px of horizontal "
        "scroll"
    )


# --------------------------------------------- defects 1-3: the device-flow dialog

@pytest.fixture
def connect_dialog(qt_app, tmp_path, monkeypatch):
    from opennest.ui.github_connect import ConnectGitHubDialog

    monkeypatch.setattr(auth, "CLIENT_ID", "Iv1.test0client0id")
    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    # The dialog opens a browser as soon as the code arrives. Nothing in a test should.
    monkeypatch.setattr("opennest.ui.github_connect.webbrowser.open", lambda _url: True)
    dialog = ConnectGitHubDialog(
        None,
        credentials=keychain.Credentials(backend=FakeKeyring()),
        transport=_CodeTransport(),
    )
    dialog.show()
    qt_app.processEvents()
    yield dialog
    dialog._timer.stop()
    dialog.deleteLater()


def test_every_visible_button_label_fits_its_button(connect_dialog, qt_app):
    """Defect 1: the row rendered "Open GitHub agai".

    Four buttons -- Connect, Copy code, Open GitHub again, Cancel -- wanted more width
    than a 460 px dialog had, and Connect was still on screen doing nothing but taking
    up room. Asserting on the *size hint* rather than on the pixels is what makes this a
    decision test: a button narrower than its own hint is one Qt has had to squeeze.
    """
    from PySide6.QtWidgets import QPushButton

    connect_dialog._begin()
    qt_app.processEvents()

    clipped = []
    for button in connect_dialog.findChildren(QPushButton):
        if button.isHidden():
            continue
        if button.width() < button.sizeHint().width():
            clipped.append((button.text(), button.width(), button.sizeHint().width()))
    assert not clipped, f"clipped button labels: {clipped}"


def test_the_spent_connect_button_gets_out_of_the_way(connect_dialog, qt_app):
    """It is disabled and useless once the flow is running, and it cost ~120px."""
    assert not connect_dialog._connect.isHidden(), "Connect must be offered at the start"
    connect_dialog._begin()
    qt_app.processEvents()
    assert connect_dialog._connect.isHidden()


def test_a_failure_offers_connect_again(connect_dialog, qt_app, monkeypatch):
    """Hiding Connect must not strand a parent whose first attempt failed."""
    monkeypatch.setattr(
        "opennest.ui.github_connect.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
    connect_dialog._begin()
    qt_app.processEvents()
    assert connect_dialog._connect.isHidden()

    connect_dialog._fail("something went wrong")
    assert not connect_dialog._connect.isHidden()
    assert connect_dialog._connect.isEnabled()


def test_the_device_code_appears_exactly_once(connect_dialog, qt_app):
    """Defect 2: it was in ``DeviceCode.instructions`` step 3 *and* in the big label.

    The standalone label was meant to be the focal element and instead read as a
    repetition. ``auth.DeviceCode.instructions`` is deliberately left alone -- the
    duplication is fixed by the dialog owning its own step wording.
    """
    connect_dialog._begin()
    qt_app.processEvents()

    code = connect_dialog._code.user_code
    from PySide6.QtWidgets import QLabel

    appearances = [
        label.text()
        for label in connect_dialog.findChildren(QLabel)
        if not label.isHidden() and code in label.text()
    ]
    assert len(appearances) == 1, f"the code appears {len(appearances)} times: {appearances}"


def test_the_instructions_property_is_unchanged(connect_dialog):
    """Phase 9's protocol layer keeps its behaviour; only presentation moved."""
    code = auth.DeviceCode("WDJB-MJHT", "https://github.com/login/device", "dc")
    assert "Enter this code:  WDJB-MJHT" in code.instructions


def test_the_device_code_is_the_most_prominent_thing_on_the_dialog(
    connect_dialog, qt_app
):
    """Defect 3: it used ``mono_label``, which styles for monospace and not for scale.

    ``role="mono"`` resolves to 11 px in the muted text colour, so the one thing a parent
    has to read off the screen rendered *smaller and greyer* than the body text beside
    it. This asserts the rendered point size, which is what the defect was about -- not
    that a particular stylesheet rule exists.
    """
    connect_dialog._begin()
    qt_app.processEvents()

    code_px = connect_dialog._code_label.fontInfo().pixelSize()
    body_px = connect_dialog._steps.fontInfo().pixelSize()
    assert code_px > body_px * 1.5, (
        f"the code renders at {code_px}px against {body_px}px of body text"
    )
    assert connect_dialog._code_label.property("role") == "deviceCode"


def test_the_secret_half_of_the_device_code_is_still_never_shown(
    connect_dialog, qt_app
):
    """Phase 9's guarantee, re-checked because this change touched the same labels."""
    connect_dialog._begin()
    qt_app.processEvents()

    from PySide6.QtWidgets import QLabel

    secret = connect_dialog._code.device_code
    for label in connect_dialog.findChildren(QLabel):
        assert secret not in label.text()
