"""Which pictures a run produced.

DoD 34 needs a chart on screen, and the application works out which file that is by
looking rather than by asking the model where it saved something. A model reporting a
path is a model that can report the wrong one, forget to, or invent it -- the Phase 5
problem again. Comparing the directory before and after cannot be wrong about what is
on disk.
"""

from __future__ import annotations

import os
from pathlib import Path

from opennest.execution import outputs
from opennest.projects.manager import create_project


def _touch(path: Path, content: bytes = b"\x89PNG\r\n\x1a\n", *, age: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if age:
        stamp = path.stat().st_mtime - age
        os.utime(path, (stamp, stamp))
    return path


def test_a_new_picture_is_recognised_as_output(project) -> None:
    before = outputs.snapshot(project.directory)
    _touch(project.directory / "charts" / "chart.png")

    assert outputs.images_written(project.directory, before) == ["charts/chart.png"]


def test_a_picture_that_was_already_there_is_not_output(project) -> None:
    """Otherwise a Games project would show its sprite every single run."""
    _touch(project.directory / "assets" / "spaceship.png", age=60)
    before = outputs.snapshot(project.directory)

    assert outputs.images_written(project.directory, before) == []


def test_a_picture_the_run_rewrote_counts(project) -> None:
    """Pressing Run Analysis twice has to show the second chart, not the first."""
    chart = _touch(project.directory / "charts" / "chart.png", age=60)
    before = outputs.snapshot(project.directory)
    _touch(chart)

    assert outputs.images_written(project.directory, before) == ["charts/chart.png"]


def test_the_newest_picture_comes_first(project) -> None:
    before = outputs.snapshot(project.directory)
    _touch(project.directory / "charts" / "old.png", age=30)
    _touch(project.directory / "charts" / "new.png")

    produced = outputs.images_written(project.directory, before)
    assert produced[0] == "charts/new.png"
    assert set(produced) == {"charts/new.png", "charts/old.png"}


def test_files_that_are_not_pictures_are_ignored(project) -> None:
    before = outputs.snapshot(project.directory)
    _touch(project.directory / "results.csv", b"a,b\n1,2\n")
    _touch(project.directory / "notes.txt", b"hello")

    assert outputs.images_written(project.directory, before) == []


def test_internal_files_are_never_treated_as_output(project) -> None:
    """matplotlib's own font cache lives under .opennest/tmp and is not a result.

    Free, because the snapshot uses ``visible_files``, which already hides internal
    directories from the model for the same reason.
    """
    before = outputs.snapshot(project.directory)
    _touch(project.internal_dir / "tmp" / "matplotlib" / "cached.png")

    assert outputs.images_written(project.directory, before) == []


def test_the_image_suffixes_come_from_the_asset_layer() -> None:
    """One definition of "is this a picture?" in the codebase, not two."""
    assert ".png" in outputs.IMAGE_SUFFIXES
    assert ".jpg" in outputs.IMAGE_SUFFIXES
    assert ".csv" not in outputs.IMAGE_SUFFIXES
    assert ".py" not in outputs.IMAGE_SUFFIXES


def test_a_project_with_no_pictures_snapshots_empty(tmp_path: Path) -> None:
    blank = create_project("Nothing Here", "blank", root=tmp_path)
    assert outputs.snapshot(blank.directory) == {}
    assert outputs.images_written(blank.directory, {}) == []
