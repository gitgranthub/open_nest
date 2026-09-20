"""Saving, going back, and surviving a crash.

Real Git against real repositories: the value of this layer is entirely in whether it
behaves when the filesystem and Git actually get involved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opennest.projects.manager import create_project
from opennest.versioning import git_manager
from opennest.versioning.autosave import DirtyTracker, atomic_write_bytes, atomic_write_text
from opennest.versioning.checkpoint import LABEL_CREATED, VersionHistory
from opennest.versioning.git_manager import GitError, SecretsFound

pytestmark = pytest.mark.skipif(not git_manager.git_available(), reason="git not available")


@pytest.fixture
def history(tmp_path: Path) -> VersionHistory:
    project = create_project("Asteroid Game", "games", root=tmp_path)
    versions = VersionHistory(project)
    versions.start()
    return versions


def game(history: VersionHistory) -> Path:
    return history.directory / "src" / "game.py"


# --------------------------------------------------------------------------- atomic

def test_atomic_write_replaces_completely(tmp_path: Path) -> None:
    target = tmp_path / "project.json"
    atomic_write_text(target, '{"a": 1}')
    atomic_write_text(target, '{"b": 2}')
    assert target.read_text() == '{"b": 2}'


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    atomic_write_text(tmp_path / "a.json", "x")
    atomic_write_bytes(tmp_path / "b.bin", b"y")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.bin"]


def test_failed_atomic_write_keeps_the_old_contents(tmp_path: Path) -> None:
    """The point of atomicity: a crash mid-write must not destroy what was there."""
    target = tmp_path / "project.json"
    atomic_write_text(target, "original")

    class Boom(Exception):
        pass

    def exploding_encoder(_: str) -> str:
        raise Boom

    with pytest.raises(Boom):
        atomic_write_text(target, exploding_encoder("never"))
    assert target.read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["project.json"]


def test_atomic_write_creates_missing_parents(tmp_path: Path) -> None:
    atomic_write_text(tmp_path / "deep" / "nested" / "f.txt", "ok")
    assert (tmp_path / "deep" / "nested" / "f.txt").read_text() == "ok"


def test_dirty_tracker(tmp_path: Path) -> None:
    tracker = DirtyTracker()
    assert not tracker.is_dirty
    tracker.touch("src/game.py", "src/game.py", "")
    assert tracker.is_dirty and tracker.paths == ("src/game.py",)
    tracker.clear()
    assert not tracker.is_dirty


# --------------------------------------------------------------------------- git setup

def test_new_project_is_a_repository_with_a_first_checkpoint(history: VersionHistory) -> None:
    assert git_manager.is_repo(history.directory)
    checkpoints = history.checkpoints()
    assert len(checkpoints) == 1 and checkpoints[0].label == LABEL_CREATED


def test_gitignore_is_generated(history: VersionHistory) -> None:
    text = (history.directory / ".gitignore").read_text()
    for expected in ("__pycache__/", ".env", ".opennest/conversations/", "*.safetensors"):
        assert expected in text


def test_conversation_archives_are_not_committed(history: VersionHistory) -> None:
    """Section 38: chat archives stay local by default. Project memory is versioned."""
    convos = history.project.internal_dir / "conversations"
    convos.mkdir(parents=True, exist_ok=True)
    (convos / "thread_v01.jsonl").write_text('{"role": "user"}')
    (history.project.internal_dir / "project_bible.md").write_text("# Bible")
    history.save("memory added")
    tracked = subprocess.run(
        ["git", "-C", str(history.directory), "ls-files"],
        capture_output=True, text=True,
    ).stdout
    assert "conversations" not in tracked
    assert "project_bible.md" in tracked


def test_identity_is_project_local_not_global(history: VersionHistory) -> None:
    """Open Nest must not change how a parent's other repositories are attributed."""
    local = subprocess.run(
        ["git", "-C", str(history.directory), "config", "--local", "user.email"],
        capture_output=True, text=True,
    ).stdout.strip()
    assert local == git_manager.DEFAULT_AUTHOR_EMAIL
    scope = subprocess.run(
        ["git", "-C", str(history.directory), "config", "--show-origin", "user.email"],
        capture_output=True, text=True,
    ).stdout
    assert ".git/config" in scope


def test_start_is_safe_to_call_repeatedly(history: VersionHistory) -> None:
    history.start()
    history.start()
    assert len(history.checkpoints()) == 1


# --------------------------------------------------------------------------- saving

def test_saving_only_happens_when_something_changed(history: VersionHistory) -> None:
    assert history.save("nothing changed") is None
    game(history).write_text("PLAYER_SPEED = 9\n")
    assert history.save("changed speed") is not None
    assert len(history.checkpoints()) == 2


def test_checkpoints_are_newest_first(history: VersionHistory) -> None:
    for speed in (6, 7, 8):
        game(history).write_text(f"PLAYER_SPEED = {speed}\n")
        history.save(f"speed {speed}")
    labels = [c.label for c in history.checkpoints()]
    assert labels[:3] == ["speed 8", "speed 7", "speed 6"]


# --------------------------------------------------------------------------- undo

def test_undo_restores_the_previous_version(history: VersionHistory) -> None:
    """WORKORDER_01 Definition of Done step 31."""
    game(history).write_text("PLAYER_SPEED = 5\n")
    history.save("speed 5")
    game(history).write_text("PLAYER_SPEED = 99\n")
    history.save("speed 99")

    assert history.undo() is not None
    assert game(history).read_text() == "PLAYER_SPEED = 5\n"


def test_undo_is_itself_undoable(history: VersionHistory) -> None:
    """History is append-only, so going back is never destructive."""
    game(history).write_text("first\n")
    history.save("first")
    game(history).write_text("second\n")
    history.save("second")

    history.undo()
    assert game(history).read_text() == "first\n"
    history.undo()
    assert game(history).read_text() == "second\n"


def test_undo_with_no_earlier_version_does_nothing(tmp_path: Path) -> None:
    project = create_project("Fresh", "games", root=tmp_path)
    versions = VersionHistory(project)
    versions.start()
    assert not versions.can_undo
    assert versions.undo() is None


def test_undo_does_not_discard_uncommitted_work(history: VersionHistory) -> None:
    """Unsaved edits are checkpointed first, so nothing is silently thrown away."""
    game(history).write_text("saved version\n")
    history.save("saved")
    game(history).write_text("work in progress, never saved\n")

    history.undo()
    contents = [
        history.file_at(c, "src/game.py") for c in history.checkpoints()
    ]
    assert any(c and "work in progress" in c for c in contents)


def test_restoring_removes_files_added_afterwards(history: VersionHistory) -> None:
    history.save("baseline")
    baseline = history.checkpoints()[0]
    (history.directory / "src" / "extra.py").write_text("x = 1\n")
    history.save("added extra")

    history.restore(baseline)
    assert not (history.directory / "src" / "extra.py").exists()


def test_restoring_brings_back_a_deleted_file(history: VersionHistory) -> None:
    history.save("baseline")
    baseline = history.checkpoints()[0]
    game(history).unlink()
    history.save("deleted the game")

    history.restore(baseline)
    assert game(history).is_file()


def test_file_at_reads_an_earlier_version(history: VersionHistory) -> None:
    game(history).write_text("old\n")
    history.save("old")
    old_point = history.checkpoints()[0]
    game(history).write_text("new\n")
    history.save("new")
    assert history.file_at(old_point, "src/game.py") == "old\n"


# --------------------------------------------------------------------------- secrets

def test_a_commit_containing_a_key_is_refused(history: VersionHistory) -> None:
    (history.directory / "src" / "config.py").write_text(
        'OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyz0123456789"\n'
    )
    with pytest.raises(SecretsFound) as caught:
        history.save("added config")
    assert "looks like" in str(caught.value)
    assert "sk-abcdefghijk" not in str(caught.value)  # never echo the credential


def test_a_refused_commit_saves_nothing(history: VersionHistory) -> None:
    before = len(history.checkpoints())
    (history.directory / "src" / "config.py").write_text(
        'TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123"\n'
    )
    with pytest.raises(SecretsFound):
        history.save("added token")
    assert len(history.checkpoints()) == before


def test_placeholders_do_not_block_saving(history: VersionHistory) -> None:
    """Blocking obvious examples would train everyone to ignore the warning."""
    (history.directory / "src" / "config.py").write_text(
        'API_KEY = "your-api-key-here"\nOTHER = "changeme"\n'
    )
    assert history.save("placeholder config") is not None


def test_save_quietly_still_raises_for_secrets(history: VersionHistory) -> None:
    """Everything else may fail silently; a credential must not."""
    (history.directory / "src" / "c.py").write_text(
        'K = "sk-ant-abcdefghijklmnopqrstuvwxyz01234"\n'
    )
    with pytest.raises(SecretsFound):
        history.save_quietly("quiet save")


# --------------------------------------------------------------------------- recovery

def test_a_clean_close_leaves_no_crash_marker(history: VersionHistory) -> None:
    assert history.was_interrupted()
    history.finish()
    assert not history.was_interrupted()


def test_recovery_after_a_crash_saves_the_unsaved_work(history: VersionHistory) -> None:
    """Simulates the app dying: marker still present, edits uncommitted."""
    game(history).write_text("work from the session that crashed\n")

    report = history.recover()
    assert report.recovered
    assert report.message == "Your project was recovered."
    assert game(history).read_text() == "work from the session that crashed\n"


def test_recovery_is_silent_when_nothing_was_lost(history: VersionHistory) -> None:
    """Section 29A: do not expose recovery mechanics unless something needs attention."""
    report = history.recover()
    assert not report.recovered and report.message == ""


def test_recovered_work_can_still_be_stepped_back_past(history: VersionHistory) -> None:
    game(history).write_text("crashed session work\n")
    history.recover()
    history.undo()
    assert "crashed session work" not in game(history).read_text()


# --------------------------------------------------------------------------- degraded

def test_history_is_a_no_op_without_git(tmp_path: Path, monkeypatch) -> None:
    """No Git must mean a plainer experience, never a broken one."""
    project = create_project("No Git", "games", root=tmp_path)
    monkeypatch.setattr(git_manager, "git_available", lambda: False)
    versions = VersionHistory(project)
    assert not versions.enabled
    versions.start()
    versions.finish()
    assert versions.save("anything") is None
    assert versions.checkpoints() == []
    assert versions.undo() is None


def test_restoring_without_a_repository_explains_itself(tmp_path: Path) -> None:
    project = create_project("Bare", "games", root=tmp_path)
    with pytest.raises(GitError):
        git_manager.restore(project.directory, "HEAD", "nope")
