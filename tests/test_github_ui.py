"""The GitHub parts of the interface -- WORKORDER_01 sections 29A, 32, 35A.

Runs under Qt's ``offscreen`` platform, like ``tests/test_workbench.py`` and
``tests/test_wizard.py``, and for the same reason: nothing here asserts on pixels, and
everything here asserts on a decision that would regress silently.

The decisions worth pinning are mostly about honesty. A build with no OAuth App must say
so rather than showing a Connect button that cannot work; a settings page must draw
without the internet; and a backup failure must not reach the child.

**Visibility is asserted with ``isHidden()``, not ``isVisibleTo()``.** HANDOFF section 4
records that ``isVisible()`` is False on a widget nobody showed, so a test asserting
``not thing.isVisible()`` passes whatever the code does, and says to use
``isVisibleTo(parent)`` instead. That fix does not hold inside a ``QStackedWidget``:
the stack *explicitly hides* every page but the current one, so ``isVisibleTo(window)``
is False for every control on the Parent Settings page no matter what this file does.
Measured both ways -- ``isHidden()`` is the one that actually discriminates here, and
two assertions in the first draft of this file were vacuous until it was checked.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from opennest.github import auth  # noqa: E402
from opennest.github.push_queue import PushQueue  # noqa: E402
from opennest.projects.manager import create_project  # noqa: E402
from opennest.security import keychain, permissions  # noqa: E402
from opennest.versioning import git_manager  # noqa: E402
from opennest.versioning.checkpoint import VersionHistory  # noqa: E402
from tests.conftest import FakeKeyring  # noqa: E402

TOKEN = "gho_TestOnlyNotARealToken0123456789"


@pytest.fixture(scope="session")
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setattr(auth, "CLIENT_ID", "Iv1.test0client0id")
    store = keychain.Credentials(backend=FakeKeyring())
    store.save_github_token(TOKEN)
    return store


@pytest.fixture
def project_with_history(tmp_path):
    project = create_project("Asteroid Game", "games", root=tmp_path / "projects")
    VersionHistory(project).start()
    return project


# --------------------------------------------------------------- the sync driver

def test_a_checkpoint_is_queued_rather_than_pushed(
    qt_app, connected, project_with_history, tmp_path
):
    """Section 34: queue, do not block. The child's next action must start at once."""
    from opennest.ui.github_sync import GitHubSync

    controls = permissions.ParentControls()
    queue = PushQueue(path=tmp_path / "queue.json")
    sync = GitHubSync(
        qt_app, credentials=connected, controls=controls, queue=queue
    )

    assert sync.queue_project(project_with_history)
    assert len(queue) == 1
    assert queue.pending()[0].branch == "main"


def test_nothing_is_queued_when_a_parent_has_backup_off(
    qt_app, connected, project_with_history, tmp_path
):
    from opennest.ui.github_sync import GitHubSync

    controls = permissions.ParentControls(github_private_backup=False)
    queue = PushQueue(path=tmp_path / "queue.json")
    sync = GitHubSync(qt_app, credentials=connected, controls=controls, queue=queue)

    assert not sync.queue_project(project_with_history)
    assert len(queue) == 0


def test_nothing_is_queued_when_no_account_is_connected(
    qt_app, project_with_history, tmp_path, monkeypatch
):
    from opennest.ui.github_sync import GitHubSync

    monkeypatch.setattr(auth, "CLIENT_ID", "Iv1.test0client0id")
    empty = keychain.Credentials(backend=FakeKeyring())
    queue = PushQueue(path=tmp_path / "queue.json")
    sync = GitHubSync(
        qt_app, credentials=empty, controls=permissions.ParentControls(), queue=queue
    )

    assert not sync.queue_project(project_with_history)


def test_a_sweep_with_nothing_connected_does_not_touch_the_network(
    qt_app, project_with_history, tmp_path, monkeypatch
):
    """A sweep runs on a timer, so it must be safe to call when nothing is set up."""
    from opennest.ui.github_sync import GitHubSync

    def explode(*args, **kwargs):
        raise AssertionError("a sweep must not push when GitHub is not ready")

    monkeypatch.setattr(git_manager, "push", explode)
    queue = PushQueue(path=tmp_path / "queue.json")
    queue.enqueue(project_with_history.directory, "main")
    sync = GitHubSync(
        qt_app,
        credentials=keychain.Credentials(backend=FakeKeyring()),
        controls=permissions.ParentControls(),
        queue=queue,
    )
    sync.sweep()  # must simply return


def test_a_blocked_credential_is_the_one_thing_a_parent_is_told(
    qt_app, connected, project_with_history, tmp_path, monkeypatch
):
    """Section 29A: block the push, notify the parent. Offline is not news."""
    from opennest.ui.github_sync import GitHubSync

    told: list[tuple[str, str]] = []
    queue = PushQueue(path=tmp_path / "queue.json")
    queue.enqueue(project_with_history.directory, "main")
    sync = GitHubSync(
        qt_app,
        credentials=connected,
        controls=permissions.ParentControls(),
        queue=queue,
        on_problem=lambda name, message: told.append((name, message)),
    )

    findings = [git_manager.Finding("src/keys.py", 1, "an OpenAI API key")]

    def blocked(*args, **kwargs):
        raise git_manager.SecretsFound(findings)

    monkeypatch.setattr(git_manager, "push", blocked)
    outcome = queue.drain(TOKEN)
    sync._done(outcome)

    assert len(told) == 1
    assert "keys.py" in told[0][1]


def test_going_offline_tells_nobody_anything(
    qt_app, connected, project_with_history, tmp_path, monkeypatch
):
    from opennest.ui.github_sync import GitHubSync

    told: list = []
    queue = PushQueue(path=tmp_path / "queue.json")
    queue.enqueue(project_with_history.directory, "main")
    sync = GitHubSync(
        qt_app,
        credentials=connected,
        controls=permissions.ParentControls(),
        queue=queue,
        on_problem=lambda name, message: told.append((name, message)),
    )

    def offline(*args, **kwargs):
        raise git_manager.Offline("no internet")

    monkeypatch.setattr(git_manager, "push", offline)
    sync._done(queue.drain(TOKEN))

    assert told == [], "an offline retry is not something to interrupt anyone with"
    assert len(queue) == 1


# --------------------------------------------------------------- Settings

def test_settings_says_so_when_the_build_has_no_oauth_app(qt_app, tmp_path, monkeypatch):
    """Phase 8's precedent: state the absence, never offer a button that cannot work."""
    from opennest.ui.settings import SettingsWindow

    monkeypatch.setattr(auth, "CLIENT_ID", "")
    monkeypatch.setattr(
        "opennest.paths.app_support_dir", lambda: tmp_path
    )
    window = SettingsWindow(
        controls=permissions.ParentControls(path=tmp_path / "settings.json"),
        credentials=keychain.Credentials(backend=FakeKeyring()),
    )
    try:
        assert "not part of this version" in window._github_status.text()
        assert window._github_connect.isHidden()
        assert window._github_disconnect.isHidden()
    finally:
        window.deleteLater()


def test_settings_offers_connect_when_nothing_is_connected(qt_app, tmp_path, monkeypatch):
    from opennest.ui.settings import SettingsWindow

    monkeypatch.setattr(auth, "CLIENT_ID", "Iv1.test0client0id")
    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    window = SettingsWindow(
        controls=permissions.ParentControls(path=tmp_path / "settings.json"),
        credentials=keychain.Credentials(backend=FakeKeyring()),
    )
    try:
        assert "Not connected" in window._github_status.text()
        assert "always private" in window._github_status.text()
        assert not window._github_connect.isHidden(), "Connect must be offered"
        assert window._github_disconnect.isHidden()
    finally:
        window.deleteLater()


def test_settings_shows_the_account_without_reaching_the_network(
    qt_app, connected, tmp_path, monkeypatch
):
    """Drawing a settings page must not depend on the internet."""
    from opennest.setup.state import InstallationState
    from opennest.ui.settings import SettingsWindow

    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    state = InstallationState(setup_complete=True, github_account="parent-example")
    state.save(tmp_path / "installation.json")

    def explode(*args, **kwargs):
        raise AssertionError("drawing Settings must not call GitHub")

    monkeypatch.setattr(auth, "account", explode)
    window = SettingsWindow(
        controls=permissions.ParentControls(path=tmp_path / "settings.json"),
        credentials=connected,
    )
    try:
        assert "parent-example" in window._github_status.text()
        assert not window._github_disconnect.isHidden(), "Disconnect must be offered"
        assert window._github_connect.isHidden()
    finally:
        window.deleteLater()


def test_the_update_check_no_longer_claims_to_be_the_only_internet_use(
    qt_app, tmp_path, monkeypatch
):
    """Phase 9 made that sentence false, so it had to change.

    The Advanced page used to tell a parent the update check "is the only time Open Nest
    itself uses the internet". GitHub backup is a second time, and the copy has to say
    the true thing -- that the check does not use the GitHub account.
    """
    from opennest.ui.settings import SettingsWindow

    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    window = SettingsWindow(
        controls=permissions.ParentControls(path=tmp_path / "settings.json"),
        credentials=keychain.Credentials(backend=FakeKeyring()),
    )
    try:
        from PySide6.QtWidgets import QLabel

        text = " ".join(
            label.text() for label in window.findChildren(QLabel)
        )
        assert "only time" not in text
    finally:
        window.deleteLater()


def test_a_parent_can_change_the_pr_policy(qt_app, connected, tmp_path, monkeypatch):
    from opennest.ui.settings import SettingsWindow

    monkeypatch.setattr("opennest.paths.app_support_dir", lambda: tmp_path)
    controls = permissions.ParentControls(path=tmp_path / "settings.json")
    window = SettingsWindow(controls=controls, credentials=connected)
    try:
        index = window._pr_policy.findData(permissions.PR_POLICY_PULL_REQUEST)
        window._pr_policy.setCurrentIndex(index)
        assert controls.github_pr_policy == permissions.PR_POLICY_PULL_REQUEST
        # And it survives a round trip through the file.
        assert (
            permissions.ParentControls.load(tmp_path / "settings.json").github_pr_policy
            == permissions.PR_POLICY_PULL_REQUEST
        )
    finally:
        window.deleteLater()


# --------------------------------------------------------------- the wizard step

def test_the_wizard_no_longer_says_github_is_unavailable(monkeypatch):
    """Phase 8's Git step said backup "is not available in this version yet"."""
    import inspect

    from opennest.setup import wizard

    source = inspect.getsource(wizard.GitStep)
    assert "not available in" not in source
    assert "Connect GitHub" in source


def test_the_wizard_still_says_so_when_there_is_no_oauth_app(monkeypatch):
    """Both halves have to exist: the real flow, and the honest absence."""
    import inspect

    from opennest.setup import wizard

    source = inspect.getsource(wizard.GitStep)
    assert "configured()" in source
    assert "not part of\n" in source or "not part of " in source
