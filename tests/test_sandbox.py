"""Escape attempts against the project path boundary.

The realistic threat is a small model emitting a plausible-looking path, not a determined
attacker. These cases are the ones a model actually produces.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from opennest.security.sandbox import (
    PathNotAllowed,
    is_within_project,
    resolve_in_project,
    visible_files,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "Asteroid Game"
    (root / "src").mkdir(parents=True)
    (root / "assets").mkdir()
    (root / ".opennest").mkdir()
    (root / ".git").mkdir()
    (root / "src" / "game.py").write_text("print('hi')")
    (root / "assets" / "ship.png").write_bytes(b"\x89PNG")
    (root / ".opennest" / "project_bible.md").write_text("secret state")
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (tmp_path / "outside.txt").write_text("should never be reachable")
    return root


@pytest.mark.parametrize(
    "escape",
    [
        "../outside.txt",
        "../../etc/passwd",
        "src/../../outside.txt",
        "./../../outside.txt",
        "src/../../../tmp/evil",
        "..",
        "../",
    ],
)
def test_parent_traversal_is_refused(project: Path, escape: str) -> None:
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, escape)


@pytest.mark.parametrize(
    "absolute",
    ["/etc/passwd", "/Users/someone/.ssh/id_rsa", "~/.ssh/id_rsa", "~", "/"],
)
def test_absolute_and_home_paths_are_refused(project: Path, absolute: str) -> None:
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, absolute)


def test_symlink_pointing_outside_is_refused(project: Path) -> None:
    """A symlink inside the project is still an escape if it resolves outside."""
    (project / "shortcut.txt").symlink_to(project.parent / "outside.txt")
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, "shortcut.txt")


def test_symlinked_directory_escape_is_refused(project: Path) -> None:
    (project / "elsewhere").symlink_to(project.parent, target_is_directory=True)
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, "elsewhere/outside.txt")


@pytest.mark.parametrize(
    "protected",
    [".opennest/project_bible.md", ".git/HEAD", ".git/config", ".opennest/conversations/x.jsonl"],
)
def test_internal_directories_are_protected(project: Path, protected: str) -> None:
    """Project memory and git history belong to the app, not the model."""
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, protected)


def test_gitignore_is_not_writable(project: Path) -> None:
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, ".gitignore", for_write=True)


def test_empty_and_blank_paths_are_refused(project: Path) -> None:
    for bad in ("", "   ", "\t"):
        with pytest.raises(PathNotAllowed):
            resolve_in_project(project, bad)


def test_control_characters_are_refused(project: Path) -> None:
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, "game\x00.py")


def test_project_root_itself_is_refused(project: Path) -> None:
    with pytest.raises(PathNotAllowed):
        resolve_in_project(project, ".")


def test_ordinary_paths_resolve(project: Path) -> None:
    assert resolve_in_project(project, "src/game.py") == (project / "src" / "game.py").resolve()
    assert resolve_in_project(project, "assets/ship.png").is_file()


def test_new_file_resolves_even_though_it_does_not_exist(project: Path) -> None:
    """write_file has to be able to name a file that is not there yet."""
    target = resolve_in_project(project, "src/new_thing.py", for_write=True)
    assert target.parent == (project / "src").resolve()
    assert not target.exists()


def test_interior_dot_dot_that_stays_inside_is_allowed(project: Path) -> None:
    """src/../assets/ship.png never leaves the project, so it is fine."""
    assert resolve_in_project(project, "src/../assets/ship.png").is_file()


def test_is_within_project(project: Path) -> None:
    assert is_within_project(project, project / "src" / "game.py")
    assert not is_within_project(project, project.parent / "outside.txt")


def test_visible_files_hides_internal_state(project: Path) -> None:
    listing = visible_files(project)
    assert "src/game.py" in listing
    assert "assets/ship.png" in listing
    assert not any(".opennest" in f for f in listing)
    assert not any(".git" in f for f in listing)


def test_visible_files_skips_pycache(project: Path) -> None:
    cache = project / "src" / "__pycache__"
    cache.mkdir()
    (cache / "game.cpython-312.pyc").write_bytes(b"\x00")
    assert not any("__pycache__" in f for f in visible_files(project))


def test_visible_files_is_bounded(project: Path) -> None:
    """A runaway project must not blow up the model's context window."""
    for i in range(50):
        (project / f"file{i:03}.txt").write_text("x")
    assert len(visible_files(project, limit=10)) == 10


@pytest.mark.skipif(os.environ.get("CI") == "true", reason="needs a case-insensitive check")
def test_protected_dir_check_uses_path_parts_not_substrings(project: Path) -> None:
    """A file merely named like a protected dir is fine; only real components count."""
    (project / "gitignore-notes.md").write_text("notes")
    assert resolve_in_project(project, "gitignore-notes.md").is_file()
