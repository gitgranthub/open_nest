"""The update protocol — decision D9, and WORKORDER_01's "Repository update behavior".

D9 draws a hard line and most of these tests are about where it is: Open Nest may
*notice* that a new version exists, and may finish an update after someone else ran
``git pull``. It may not pull, merge, reset or otherwise touch its own checkout, and a
one-click in-app updater is a separate product feature.

The other theme is DoD 52's list of things an update must never lose. Most of that is
true by layout — projects, their Git history and their memory all live outside the
repository, and credentials are not in the filesystem at all — so what is tested here
is the part that is not free: that a failed migration does not record success, and that
an expensive change is reported rather than started.
"""

from __future__ import annotations

import subprocess

from opennest.setup import migration, updates
from opennest.setup.state import Change, Fingerprint, InstallationState

# --------------------------------------------------------------------- the check

def test_a_repository_without_git_says_so_rather_than_failing(tmp_path) -> None:
    status = updates.check(tmp_path)
    assert status.outcome == "unknown"
    assert status.available is False
    assert status.checked is False


def test_being_offline_is_an_answer_not_an_error(tmp_path, monkeypatch) -> None:
    """Open Nest is offline-first; a failed check is a sentence, not a stack trace."""
    (tmp_path / ".git").mkdir()

    def only_local(root, *args, timeout):
        return "a" * 40 if args[:1] == ("rev-parse",) else None

    monkeypatch.setattr(updates, "_git", only_local)
    status = updates.check(tmp_path)
    assert status.outcome == "unknown"
    assert "could not reach" in status.summary.lower()
    assert "offline" in status.detail.lower()


def test_an_unmoved_remote_reports_up_to_date(tmp_path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updates, "_local_commit", lambda root, timeout: "a" * 40)
    monkeypatch.setattr(updates, "_current_branch", lambda root, timeout: "main")
    monkeypatch.setattr(updates, "_remote_commit", lambda root, b, timeout: (True, "a" * 40))

    status = updates.check(tmp_path)
    assert status.outcome == "current"
    assert status.available is False


def test_a_moved_remote_reports_an_update_and_what_to_do(tmp_path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updates, "_local_commit", lambda root, timeout: "a" * 40)
    monkeypatch.setattr(updates, "_current_branch", lambda root, timeout: "main")
    monkeypatch.setattr(updates, "_remote_commit", lambda root, b, timeout: (True, "b" * 40))

    status = updates.check(tmp_path)
    assert status.available is True
    # The parent-facing next step, because Phase 8 deliberately does not pull.
    assert "git pull" in status.detail


def test_a_branch_the_remote_does_not_have_is_not_blamed_on_the_network(
    tmp_path, monkeypatch
) -> None:
    """``ls-remote`` exits 0 with empty output for an unknown branch.

    Found by the Phase 8 acceptance pass, running on a branch that had not been
    pushed: the check said "could not reach GitHub" on a machine whose network was
    working perfectly.
    """
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updates, "_local_commit", lambda root, timeout: "a" * 40)
    monkeypatch.setattr(updates, "_current_branch", lambda root, timeout: "a-new-branch")
    monkeypatch.setattr(updates, "_remote_commit", lambda root, b, timeout: (True, None))

    status = updates.check(tmp_path)
    assert status.outcome == "unknown"
    assert "could not reach" not in status.summary.lower()
    assert "a-new-branch" in status.detail


def test_an_unreachable_remote_is_still_reported_as_unreachable(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(updates, "_local_commit", lambda root, timeout: "a" * 40)
    monkeypatch.setattr(updates, "_current_branch", lambda root, timeout: "main")
    monkeypatch.setattr(updates, "_remote_commit", lambda root, b, timeout: (False, None))

    status = updates.check(tmp_path)
    assert "could not reach" in status.summary.lower()


def test_the_two_failures_are_told_apart_from_real_git_output(tmp_path, monkeypatch) -> None:
    """The distinction has to survive at the ``_remote_commit`` level, not just above it."""
    monkeypatch.setattr(updates, "_git", lambda root, *a, timeout: None)
    assert updates._remote_commit(tmp_path, "main", 5) == (False, None)

    monkeypatch.setattr(updates, "_git", lambda root, *a, timeout: "")
    assert updates._remote_commit(tmp_path, "main", 5) == (True, None)

    monkeypatch.setattr(
        updates, "_git", lambda root, *a, timeout: "abc123\trefs/heads/main")
    assert updates._remote_commit(tmp_path, "main", 5) == (True, "abc123")


def test_the_check_only_ever_runs_read_only_git_commands(tmp_path, monkeypatch) -> None:
    """The boundary D9 draws, enforced rather than intended.

    A future change that reaches for ``git fetch`` or ``git pull`` here fails this.
    """
    (tmp_path / ".git").mkdir()
    issued: list = []

    def record(command, **kwargs):
        issued.append(command)
        return subprocess.CompletedProcess(command, 1, b"", b"")

    monkeypatch.setattr(updates.subprocess, "run", record)
    updates.check(tmp_path)

    forbidden = {"pull", "fetch", "merge", "reset", "checkout", "clean", "stash", "push"}
    for command in issued:
        assert not forbidden.intersection(command), command
        assert command[:1] == ["git"]


def test_the_check_writes_nothing_to_disk(tmp_path, monkeypatch) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "file.txt").write_text("unchanged")
    monkeypatch.setattr(updates, "_local_commit", lambda root, timeout: "a" * 40)
    monkeypatch.setattr(updates, "_current_branch", lambda root, timeout: "main")
    monkeypatch.setattr(updates, "_remote_commit", lambda root, b, timeout: (True, "b" * 40))

    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    updates.check(tmp_path)
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


# --------------------------------------------------------------------- the migration

def _stale(**fingerprint) -> InstallationState:
    state = InstallationState(setup_complete=True)
    state.fingerprint = Fingerprint(
        app_version="0.0.1", requirements={"base.txt": "old"}, **fingerprint
    )
    return state


def test_an_unchanged_checkout_needs_no_migration() -> None:
    state = InstallationState(setup_complete=True)
    state.record_launch()
    assert migration.plan(state).needed is False


def test_a_changed_manifest_asks_to_reinstall() -> None:
    plan = migration.plan(_stale())
    assert plan.needed is True
    assert plan.reinstall_dependencies is True
    assert "updated" in plan.headline()


def test_a_moved_model_pin_is_reported_and_never_downloaded() -> None:
    """PLAN.md: gigabytes, so it is shown and nothing starts on its own."""
    state = InstallationState(setup_complete=True)
    state.fingerprint = Fingerprint(
        app_version="0.1.0", model_pins={"qwen3-4b-instruct": "old-sha"}
    )
    plan = migration.plan(state)
    assert plan.models_to_refresh
    assert plan.automatic is False, "this one needs the parent, so it is not automatic"


def test_applying_records_the_new_checkout(tmp_path) -> None:
    state = _stale()
    state.path = tmp_path / "installation.json"
    plan = migration.plan(state)
    result = migration.apply(state, plan, runner=lambda manifests: 0)

    assert result.ok is True
    assert state.pending_changes() == (), "the new checkout should now be the known one"


def test_a_failed_reinstall_does_not_record_success(tmp_path) -> None:
    """Otherwise the next launch believes the update finished, and it did not."""
    state = _stale()
    state.path = tmp_path / "installation.json"
    plan = migration.plan(state)
    result = migration.apply(state, plan, runner=lambda manifests: 1)

    assert result.ok is False
    assert state.pending_changes(), "the update should still be pending"
    assert "projects are untouched" in result.message


def test_a_migration_reports_progress_a_parent_can_read(tmp_path) -> None:
    state = _stale()
    state.path = tmp_path / "installation.json"
    said: list = []
    migration.apply(
        state, migration.plan(state),
        on_progress=said.append, runner=lambda manifests: 0,
    )
    assert said, "a slow step with no message reads as a hang"
    assert all(message.endswith("...") for message in said)


def test_a_migration_never_touches_a_project(tmp_path) -> None:
    """DoD 52. Mostly true by layout, and worth a test that says so out loud."""
    projects = tmp_path / "projects"
    (projects / "spaceship" / ".opennest").mkdir(parents=True)
    (projects / "spaceship" / "main.py").write_text("print('hello')")
    (projects / "spaceship" / ".opennest" / "project_bible.md").write_text("# Bible")

    state = _stale()
    state.path = tmp_path / "installation.json"
    before = {p: p.read_bytes() for p in projects.rglob("*") if p.is_file()}
    migration.apply(state, migration.plan(state), runner=lambda manifests: 0)
    after = {p: p.read_bytes() for p in projects.rglob("*") if p.is_file()}
    assert before == after


def test_nothing_is_migrated_for_an_installation_that_was_never_set_up() -> None:
    """A fresh Mac has not been "updated", and must not be shown an update prompt."""
    assert migration.plan(InstallationState()).needed is False


def test_the_plan_lists_every_change_in_readable_words() -> None:
    state = _stale(profiles_schema=1, model_pins={"qwen3-4b-instruct": "old"})
    plan = migration.plan(state)
    assert plan.lines()
    for line in plan.lines():
        assert isinstance(line, str) and line.endswith(".")


def test_a_costly_change_is_flagged_on_the_change_itself() -> None:
    """So a caller cannot mistake "new model offered" for "re-download 2 GB"."""
    costly = Change("models", "A new version is available.", costly=True)
    cheap = Change("models", "New AI models are available.")
    assert costly.costly is True and cheap.costly is False
