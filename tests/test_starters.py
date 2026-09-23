"""Starter kits: what they are, what applying one does, and what it must never do.

Section 18 of the Phase 11 work order lists the checks a starter needs. The ones that
are facts about the shipped data -- manifests parse, declared files exist, ids match
directories, entry points match profiles -- live in ``test_config.py`` beside the other
configuration guards. This file is about behaviour: copying, refusing, recording, and
the empty project that is now a supported state rather than a bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opennest.agent.controller import project_state
from opennest.projects import starters
from opennest.projects.manager import (
    PROFILE_DEFAULT,
    ProjectError,
    add_starter,
    create_project,
    open_project,
    read_manifest,
)
from opennest.projects.profiles import load_profiles

ALL_PROFILES = [profile.id for profile in load_profiles()]


# --------------------------------------------------------------------------- applying

def test_a_starter_is_copied_in_and_recorded(tmp_path: Path) -> None:
    """Section 12: the fact that a foundation exists is deterministic project state.

    Recorded rather than inferred, so nothing has to guess from filenames later.
    """
    project = create_project("Arcade", "website", root=tmp_path)
    assert project.manifest.starter_id == "website_basic"
    assert project.manifest.starter_version == 1

    src = project.directory / "src"
    for name in ("index.html", "styles.css", "script.js"):
        assert (src / name).is_file(), name
    assert (src / "assets").is_dir(), "the starter's declared directory was not created"

    # And it survives a reopen, because it is in project.json rather than in memory.
    assert read_manifest(project.directory).starter_id == "website_basic"


def test_copying_a_starter_does_not_touch_the_shipped_files(tmp_path: Path) -> None:
    """Section 18: copying never modifies source resources.

    The kit is installed once and used by every project on the Mac, so a project that
    could write back into it would corrupt the next child's starting point.
    """
    starter = starters.get_starter("website_basic")
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(starter.directory.rglob("*"))
        if path.is_file()
    }
    project = create_project("Arcade", "website", root=tmp_path)
    (project.directory / "src" / "index.html").write_text("changed", encoding="utf-8")

    after = {
        path: (path.stat().st_mtime_ns, path.read_bytes())
        for path in sorted(starter.directory.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_starting_empty_puts_nothing_in_the_project(tmp_path: Path) -> None:
    """Section 61: choosing Start Empty must actually be empty.

    The directories are still made -- a project needs somewhere to put things -- but
    nothing is written into src/, and nothing is recorded as a starter.
    """
    project = create_project("From Nothing", "website", starter_id=None, root=tmp_path)
    assert list((project.directory / "src").iterdir()) == []
    assert project.manifest.starter_id is None
    assert project.manifest.starter_version is None


def test_blank_starts_empty_without_being_asked(tmp_path: Path) -> None:
    """Section 7: Blank stays genuinely blank, and offers nothing to decline."""
    profile = next(p for p in load_profiles() if p.id == "blank")
    assert profile.starters == ()
    assert profile.starter_default is None

    project = create_project("An Idea", "blank", root=tmp_path)
    assert list((project.directory / "src").iterdir()) == []
    assert project.manifest.starter_id is None


@pytest.mark.parametrize("profile_id", ALL_PROFILES)
def test_every_profile_can_be_started_empty(tmp_path: Path, profile_id: str) -> None:
    project = create_project("Empty One", profile_id, starter_id=None, root=tmp_path)
    assert not starters.has_own_files(project.directory / "src")


def test_the_default_is_not_the_same_thing_as_choosing_empty(tmp_path: Path) -> None:
    """``PROFILE_DEFAULT`` is "nobody chose"; ``None`` is "they chose nothing"."""
    chosen = create_project("Chosen", "games", starter_id=None, root=tmp_path)
    defaulted = create_project(
        "Defaulted", "games", starter_id=PROFILE_DEFAULT, root=tmp_path
    )
    assert chosen.manifest.starter_id is None
    assert defaulted.manifest.starter_id == "pygame_basic"


def test_a_profile_cannot_be_given_a_starter_it_does_not_offer(tmp_path: Path) -> None:
    with pytest.raises(ProjectError) as caught:
        create_project("Wrong", "games", starter_id="website_basic", root=tmp_path)
    assert "no starter called" in str(caught.value)


# --------------------------------------------------------------- adding one afterwards

def test_a_starter_can_be_added_to_a_project_that_started_empty(tmp_path: Path) -> None:
    """Section 9's one-click offer, and the state it leaves behind."""
    project = create_project("Later", "website", starter_id=None, root=tmp_path)
    written = add_starter(project, "website_basic")

    assert set(written) == {"index.html", "styles.css", "script.js"}
    assert (project.directory / "src" / "index.html").is_file()
    assert project.manifest.starter_id == "website_basic"
    assert read_manifest(project.directory).starter_version == 1


def test_adding_a_starter_never_overwrites_existing_work(tmp_path: Path) -> None:
    """Section 9, and the worst bug this feature could have.

    Enforced in ``starters.apply`` rather than in whichever button calls it: a rule that
    only holds when the caller remembers is not a rule.
    """
    project = create_project("Mine", "website", starter_id=None, root=tmp_path)
    page = project.directory / "src" / "index.html"
    page.write_text("<h1>MY OWN PAGE</h1>", encoding="utf-8")

    with pytest.raises(ProjectError):
        add_starter(project, "website_basic")

    assert page.read_text(encoding="utf-8") == "<h1>MY OWN PAGE</h1>"
    # And nothing else was half-written on the way to failing.
    assert not (project.directory / "src" / "styles.css").exists()
    assert project.manifest.starter_id is None


def test_the_refusal_names_the_file_that_is_in_the_way(tmp_path: Path) -> None:
    project = create_project("Mine", "website", starter_id=None, root=tmp_path)
    (project.directory / "src" / "styles.css").write_text("body{}", encoding="utf-8")
    with pytest.raises(ProjectError) as caught:
        add_starter(project, "website_basic")
    assert "styles.css" in str(caught.value)


def test_an_empty_src_is_recognised_as_empty(tmp_path: Path) -> None:
    """What decides whether the one-click offer is safe to show at all."""
    project = create_project("Empty", "website", starter_id=None, root=tmp_path)
    source = project.directory / "src"
    assert not starters.has_own_files(source)

    # A dotfile is housekeeping, not work.
    (source / ".DS_Store").write_bytes(b"")
    assert not starters.has_own_files(source)

    (source / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    assert starters.has_own_files(source)


# ------------------------------------------------------------------ what Gary is told

def test_gary_is_told_which_starter_a_project_began_from(tmp_path: Path) -> None:
    """Section 13: he should not ask "are you using HTML?" about a Basic Website."""
    project = create_project("Arcade", "website", root=tmp_path)
    state = project_state(project)
    assert "Basic Website" in state
    assert "starter" in state.lower()


def test_gary_is_told_the_starter_files_are_the_childs_to_change(tmp_path: Path) -> None:
    """Section 14: a starter is a beginning, not protected boilerplate."""
    project = create_project("Arcade", "website", root=tmp_path)
    state = project_state(project)
    assert "the child's now" in state


def test_gary_is_told_nothing_about_a_starter_when_there_was_none(tmp_path: Path) -> None:
    """Silence, rather than a claim about a project nobody measured.

    Covers two cases at once: a project started empty, and one made before Phase 11
    whose manifest has no starter fields at all.
    """
    empty = create_project("From Nothing", "website", starter_id=None, root=tmp_path)
    assert "starter" not in project_state(empty).lower()

    old = create_project("Old", "games", root=tmp_path)
    manifest = old.directory / "project.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8")
        .replace('"starter_id": "pygame_basic",', "")
        .replace('"starter_version": 1,', ""),
        encoding="utf-8",
    )
    reopened = open_project(old.directory)
    assert reopened.manifest.starter_id is None
    assert "starter" not in project_state(reopened).lower()


def test_a_manifest_written_before_phase_11_still_opens(tmp_path: Path) -> None:
    """The migration question: old project data stays readable."""
    project = create_project("Old", "games", root=tmp_path)
    (project.directory / "project.json").write_text(
        '{"name": "Old", "profile": "games", "created": "2026-01-01T00:00:00+00:00",'
        ' "entrypoint": "game.py", "schema_version": 1}',
        encoding="utf-8",
    )
    reopened = open_project(project.directory)
    assert reopened.name == "Old"
    assert reopened.manifest.starter_id is None
    assert reopened.manifest.starter_version is None


def test_a_withdrawn_starter_is_still_named_rather_than_forgotten(tmp_path: Path) -> None:
    """A kit removed in a later release does not erase what a project began from."""
    project = create_project("Arcade", "website", root=tmp_path)
    project.manifest.starter_id = "some_withdrawn_kit"
    project.save()
    state = project_state(open_project(project.directory))
    assert "some_withdrawn_kit" in state
